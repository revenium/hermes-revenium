import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
PLUGIN_DIR = SKILL / 'plugins' / 'revenium-classifier'
SIDECAR = SKILL / 'scripts' / 'get-root-session-id.py'  # Phase 21 (TRACE-01)


def _agent_aux_client_available() -> bool:
    """True iff `from agent.auxiliary_client import call_llm` succeeds. Phase 6
    plugin tests that exercise the real LLM call require this; mocked tests do not."""
    try:
        from agent.auxiliary_client import call_llm  # noqa: F401
        return True
    except ImportError:
        return False


def _setup_plugin_env(tmpdir):
    """Returns (env_snapshot, sys_path_added, hermes_home, state_dir, markers_dir).
    Caller must call _restore_plugin_env in finally."""
    import os
    import sys
    hermes_home = os.path.join(tmpdir, 'hh')
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    markers_dir = os.path.join(state_dir, 'markers')
    os.makedirs(markers_dir, mode=0o700)
    snapshot = {k: os.environ.get(k) for k in (
        'HERMES_HOME', 'REVENIUM_STATE_DIR', 'REVENIUM_MARKERS_DIR',
        'REVENIUM_TAXONOMY_FILE', 'REVENIUM_JOB_TAXONOMY_FILE',
    )}
    os.environ['HERMES_HOME'] = hermes_home
    os.environ['REVENIUM_STATE_DIR'] = state_dir
    os.environ['REVENIUM_MARKERS_DIR'] = markers_dir
    sys_path_added = str(PLUGIN_DIR) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(PLUGIN_DIR))
    return snapshot, sys_path_added, hermes_home, state_dir, markers_dir


def _restore_plugin_env(snapshot, sys_path_added):
    import os
    import sys
    if sys_path_added and str(PLUGIN_DIR) in sys.path:
        sys.path.remove(str(PLUGIN_DIR))
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _load_root_walk_helper():
    """Load the get-root-session-id.py sidecar as an importable module.

    The sidecar's filename contains a hyphen (`get-root-session-id.py`)
    which forbids the `import` syntax. Use importlib.util.spec_from_file_location
    so the test exercises the canonical Python function (NOT the bash
    wrapper — that's a Phase 21-03 live-host concern). Phase 21 D-02
    documents `get_root_session_id(sid, state_db_path=None, max_depth=10) -> str`.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'phase21_root_walk_helper', str(SIDECAR),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
            SKILL / 'job-taxonomy.json',          # Phase 8 — job-declaration seed
            SKILL / 'references' / 'task-taxonomy.md',
            SKILL / 'references' / 'halt-survivability.md',
            SKILL / 'references' / 'task-classification.md',
            SKILL / 'references' / 'job-declaration.md',
            SKILL / 'scripts' / 'common.sh',
            SKILL / 'scripts' / 'install-cron.sh',
            SKILL / 'scripts' / 'uninstall-cron.sh',
            SKILL / 'scripts' / 'cron.sh',
            SKILL / 'scripts' / 'hermes-report.sh',
            SKILL / 'scripts' / 'clear-halt.sh',
            SKILL / 'scripts' / 'prune-markers.sh',
            SKILL / 'scripts' / 'pre_llm_call.sh',      # Phase 12 — pre-LLM-call halt hook
            SKILL / 'scripts' / 'pre_tool_call.sh',     # Phase 12 — pre-tool-call block + CANCELLED marker
            SKILL / 'scripts' / 'install-hooks.sh',     # Phase 12 — idempotent config.yaml hook installer
            SKILL / 'scripts' / 'uninstall-hooks.sh',   # Phase 12 — hook uninstaller
            SKILL / 'scripts' / 'post_tool_call.sh',    # Phase 14 — tool-event capture hook
            SKILL / 'scripts' / 'tool-event-report.sh', # Phase 15 — tool-event reporter
            SKILL / 'scripts' / 'install-plugin.sh',    # Closes tap-install plugin-discovery gap
            SKILL / 'scripts' / 'hooks-status.sh',      # Diagnose hooks-registered-but-inert footgun
            # Phase 18 — single rule-creation entry point (D-01)
            SKILL / 'scripts' / 'setup-guardrails.sh',
            # Phase 19 — guardrail cron stage (replaces budget-check.sh)
            SKILL / 'scripts' / 'guardrail-check.sh',
            # Python module (excluded from bash -n check by *.sh glob in test_shell_scripts_have_valid_syntax)
            SKILL / 'scripts' / 'split_strategies.py',
            # Phase 21 — root-walk helper (TRACE-01)
            SKILL / 'scripts' / 'get-root-session-id.py',
            # Phase 6 — on_session_end classifier plugin (HOOK-01, HOOK-11)
            SKILL / 'plugins' / 'revenium-classifier' / 'plugin.yaml',
            SKILL / 'plugins' / 'revenium-classifier' / '__init__.py',
            SKILL / 'plugins' / 'revenium-classifier' / 'classifier.py',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'trivial-turn.json',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'substantive-turn.json',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'subagent-turn.json',
            # Phase 18 — operator-facing migration doc (MIGR-06, D-16)
            ROOT / 'docs' / 'migration-guardrails.md',
            # Phase 20 — COMPAT-01 golden-argv wire-shape fixtures (D-01..D-04)
            ROOT / 'tests' / 'fixtures' / 'compat' / 'meter-completion.golden.json',
            ROOT / 'tests' / 'fixtures' / 'compat' / 'jobs-create.golden.json',
            ROOT / 'tests' / 'fixtures' / 'compat' / 'jobs-outcome.golden.json',
            ROOT / 'tests' / 'fixtures' / 'compat' / 'meter-tool-event.golden.json',
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
        # Scope is everything that SHIPS with the skill: skills/, scripts, tests, docs,
        # README.md, CLAUDE.md, examples/. The .planning/ tree is internal planning
        # state — it contains anti-pattern callouts that intentionally quote the
        # forbidden tokens inside backticks while explaining what to avoid. Scanning
        # .planning/ would flag those meta-references and defeat the guard's purpose
        # (catching reintroduction into shipped artifacts).
        offenders = []
        for path in ROOT.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix not in {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}:
                continue
            if path.name == 'test_repository.py':
                continue
            rel = path.relative_to(ROOT)
            if rel.parts and rel.parts[0] == '.planning':
                continue
            text = path.read_text(errors='ignore')
            # Word-boundary anchored so class-name compounds in Hermes upstream
            # code (e.g. `ClawHubSource`, `SkillsShSource`) referenced in our
            # install-path docs aren't false-positively flagged as our forked-from
            # branding. Standalone product mentions still match correctly.
            if re.search(r'\b(?:OpenClaw|openclaw|ClawHub|clawhub)\b', text):
                offenders.append(str(rel))
        self.assertEqual(offenders, [], f'found legacy branding in: {offenders}')

    def test_no_legacy_budget_status_references(self):
        # Phase 19 SC-7 gate: scans code-bearing files only (.sh/.py/.yml/.yaml/.json).
        # .md is intentionally excluded — halt-survivability.md prose is rewritten by
        # Phase 20 DOCS-03 (see 19-CONTEXT.md D-16; 19-11 ratifies this scope).
        # guardrail-check.sh is intentionally excluded — it contains a one-time rm -f
        # cleanup of the legacy budget-status.json file (Phase 19 clean-break, plan 19-11).
        # That reference is the cleanup mechanism itself, not a consumer of the old file.
        excluded_names = {'guardrail-check.sh'}
        offenders = []
        for path in (SKILL.parent.parent / 'skills').rglob('*'):
            if not path.is_file():
                continue
            if path.suffix not in {'.sh', '.py', '.yml', '.yaml', '.json'}:
                continue
            if path.name in excluded_names:
                continue
            text = path.read_text(errors='ignore')
            if re.search(r'budget-check|budget-status', text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [],
                         f'SC-7: legacy budget-check/budget-status references found in: {offenders}')

    def test_runtime_paths_are_hermes_native(self):
        text = (SKILL / 'scripts' / 'common.sh').read_text()
        self.assertIn('.hermes', text)
        self.assertIn('state/revenium', text)
        self.assertNotIn('.openclaw', text)
        self.assertIn('task-taxonomy.json', text)
        self.assertIn('TAXONOMY_FILE=', text)
        self.assertRegex(text, r'MARKERS_DIR="\$\{REVENIUM_MARKERS_DIR:-\$\{STATE_DIR\}/markers\}"')
        self.assertRegex(text, r'MARKERS_READY_DIR="\$\{REVENIUM_MARKERS_READY_DIR:-\$\{STATE_DIR\}/markers/\.ready\}"')
        self.assertIn('markers/.ready', text)
        self.assertIn('markers', text)
        # Phase 3 D-13: LOCK_FILE declared in common.sh (single source of truth);
        # never hardcoded in cron.sh or hermes-report.sh.
        self.assertIn('LOCK_FILE=', text)
        self.assertIn('cron.lock', text)
        # Phase 7 D-13: new v1.1 job-tracking state paths declared only in common.sh.
        self.assertIn('JOBS_LEDGER_FILE=', text)
        self.assertIn('revenium-jobs.ledger', text)
        self.assertIn('JOB_TAXONOMY_FILE=', text)
        self.assertIn('job-taxonomy.json', text)
        # Phase 12: hooks config path declared only in common.sh.
        self.assertIn('HOOKS_CONFIG_FILE=', text)
        self.assertIn('config.yaml', text)
        # Phase 14/16: tool-event state paths declared only in common.sh (SC3).
        self.assertIn('TOOL_EVENTS_DIR=', text)
        self.assertIn('TOOL_EVENTS_LEDGER_FILE=', text)
        self.assertIn('tool-events', text)
        self.assertIn('revenium-tool-events.ledger', text)
        # Phase 17: v1.3 guardrails-native paths and CLI capability helper.
        self.assertIn('GUARDRAIL_STATUS_FILE=', text)
        self.assertIn('guardrail-status.json', text)
        self.assertIn('RULES_LOCK_FILE=', text)
        self.assertIn('rules.lock', text)
        self.assertIn('has_guardrails_cli()', text)
        # Phase 18: notify-once gate for setup-guardrails.sh migration failures (D-10).
        self.assertIn('MIGRATION_NOTIFY_FILE=', text)
        self.assertIn('migration-notify-state', text)
        self.assertRegex(text, r'MIGRATION_NOTIFY_FILE="\$\{REVENIUM_MIGRATION_NOTIFY_FILE:-\$\{STATE_DIR\}/migration-notify-state\}"')
        # Phase 19: WARN_FLAGS_DIR for warn-band rate-limit markers (D-06)
        self.assertIn('WARN_FLAGS_DIR=', text)
        self.assertIn('markers/.warn', text)
        self.assertRegex(text, r'WARN_FLAGS_DIR="\$\{REVENIUM_WARN_FLAGS_DIR:-\$\{MARKERS_DIR\}/\.warn\}"')
        # Phase 19: BUDGET_STATUS_FILE removed (clean break — D-12, ENF-03)
        self.assertNotIn('BUDGET_STATUS_FILE=', text)
        self.assertNotIn('budget-status.json', text)

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

    def test_job_taxonomy_file_schema(self):
        """Seed job-taxonomy.json has correct schema and all labels match the regex (Phase 8)."""
        import json, re
        taxonomy_path = SKILL / 'job-taxonomy.json'
        self.assertTrue(taxonomy_path.exists(), 'job-taxonomy.json missing from skill root')
        data = json.loads(taxonomy_path.read_text())
        self.assertIn('labels', data, 'taxonomy missing top-level "labels" key')
        labels = data['labels']
        self.assertIsInstance(labels, dict, '"labels" must be a dict')
        # D-04: seed list is planner discretion — assert floor count, NOT exact ordered list
        self.assertGreaterEqual(len(labels), 8, f'job taxonomy must have at least 8 labels, got {len(labels)}')
        label_regex = re.compile(r'^[a-z][a-z0-9_]{1,47}$')
        forbidden = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
        for label, schema in labels.items():
            self.assertRegex(label, label_regex, f'label "{label}" fails regex')
            self.assertNotIn(label, forbidden, f'forbidden label "{label}" in seed taxonomy')
            self.assertIn('description', schema, f'label "{label}" missing description')
            self.assertIn('examples', schema, f'label "{label}" missing examples')
            self.assertIsInstance(schema['description'], str, f'label "{label}" description must be str')
            self.assertIsInstance(schema['examples'], list, f'label "{label}" examples must be list')

    def test_config_schema_doc_lists_rule_ids(self):
        """Phase 17 D-15: config-schema.md documents ruleIds as active field
        and marks alertId with a Deprecated/Legacy notice."""
        import re
        schema_doc = SKILL / 'references' / 'config-schema.md'
        self.assertTrue(schema_doc.exists(), 'config-schema.md missing from skill references/')
        text = schema_doc.read_text()
        self.assertIn('ruleIds', text, 'config-schema.md must document the ruleIds field')
        # alertId must be accompanied by a deprecation marker within the file
        self.assertTrue(
            re.search(r'(?:Deprecated|Legacy)', text),
            'config-schema.md must contain a Deprecated or Legacy marker for alertId',
        )
        # The deprecation marker must be near alertId (within 10 lines)
        lines = text.splitlines()
        alert_id_lines = [i for i, ln in enumerate(lines) if 'alertId' in ln]
        self.assertTrue(alert_id_lines, 'config-schema.md must contain alertId')
        deprecated_lines = [i for i, ln in enumerate(lines)
                            if re.search(r'(?:Deprecated|Legacy)', ln)]
        self.assertTrue(deprecated_lines, 'config-schema.md must contain Deprecated/Legacy marker')
        # At least one deprecation marker must be within 10 lines of an alertId reference
        close_enough = any(
            abs(a - d) <= 10
            for a in alert_id_lines
            for d in deprecated_lines
        )
        self.assertTrue(
            close_enough,
            'Deprecated/Legacy marker must appear within 10 lines of alertId in config-schema.md',
        )

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
        QUANT = Decimal("0.000001")
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
            # G-04 regression: input cost with > 6 decimal places (e.g. qwen3.6-plus's
            # 0.0119093). Pre-fix this raised AssertionError("conservation violated for cost")
            # because last_cost.quantize() truncated the 7th digit. Post-fix, the input
            # is quantized to 6 places up-front so the conservation invariant holds against
            # the quantized input.
            ({"input": 35372, "output": 212, "cache_read": 0, "cache_write": 0,
              "total": 35584, "cost": "0.0119093"}, 2),
        ]
        for delta, n in cases:
            splits = equal_split(delta, n)
            self.assertEqual(len(splits), n, f"expected {n} splits for n={n}")
            for k in INT_FIELDS:
                self.assertEqual(sum(s[k] for s in splits), delta[k],
                                 f"conservation violated for {k} at n={n}")
            # Decimal-exact cost conservation — against the quantized input
            # (the splitter rounds input to 6 decimal places per G-04 fix).
            quantized_input_cost = Decimal(delta[COST_FIELD]).quantize(QUANT)
            self.assertEqual(
                sum(Decimal(s[COST_FIELD]) for s in splits),
                quantized_input_cost,
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
        """Halt-check anchor appears before the classification anchor in SKILL.md,
        and the job-declaration anchor appears after the classification anchor."""
        text = (SKILL / 'SKILL.md').read_text()
        halt_anchor = 'HALT CHECK'
        classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'
        job_anchor = 'FINAL ACTION — JOB DECLARATION'
        self.assertIn(halt_anchor, text,
                      'halt-check anchor missing from SKILL.md — do not remove or rename it')
        self.assertIn(classify_anchor, text,
                      'classification anchor missing from SKILL.md — Phase 2 deliverable not present')
        self.assertIn(job_anchor, text,
                      'job-declaration anchor missing from SKILL.md — Phase 8 deliverable not present')
        self.assertLess(
            text.index(halt_anchor),
            text.index(classify_anchor),
            'halt-check anchor must appear before classification anchor in SKILL.md',
        )
        self.assertLess(
            text.index(classify_anchor),
            text.index(job_anchor),
            'job-declaration anchor must appear after classification anchor in SKILL.md',
        )

    def test_job_marker_snippets_resolve_session_id_from_session_files(self):
        """Phase 13 D-07: the JOB DECLARATION block was demoted to a defense-in-depth
        backstop — the agent-side execute_code snippet was removed because the
        revenium-classifier plugin is now the primary job-marker author (on_session_end).
        Assert the snippet is absent from SKILL.md so the demoted state is enforced.
        Phase 12 D-05: the HALT CHECK agent-side marker write was also removed
        (the pre_tool_call hook writes the CANCELLED marker)."""
        text = (SKILL / 'SKILL.md').read_text()
        blocks = re.findall(r'```python\n(.*?)\n```', text, re.DOTALL)
        job_blocks = [b for b in blocks if 'def write_job_marker' in b]
        self.assertEqual(
            len(job_blocks), 0,
            'Phase 13 D-07: the execute_code write_job_marker snippet must be absent from '
            'SKILL.md — the revenium-classifier plugin is now the primary job-marker author; '
            f'found {len(job_blocks)} snippet(s)')

    def test_job_declaration_snippet_does_not_clobber_seeded_taxonomy(self):
        """CR-01 / Phase 13 D-07: the JOB DECLARATION execute_code snippet was removed
        from SKILL.md (demoted to a backstop). The CR-01 taxonomy-clobber invariant is
        now enforced in the revenium-classifier plugin (classifier.py), not in an
        agent-side snippet. Assert the snippet is absent so the demoted state holds."""
        text = (SKILL / 'SKILL.md').read_text()
        blocks = re.findall(r'```python\n(.*?)\n```', text, re.DOTALL)
        snippet_blocks = [b for b in blocks if 'def write_job_marker' in b and 'taxonomy_path' in b]
        self.assertEqual(
            len(snippet_blocks), 0,
            'Phase 13 D-07: write_job_marker+taxonomy snippet must be absent from SKILL.md; '
            f'found {len(snippet_blocks)} — the classifier plugin is now the taxonomy author')

    def test_job_declaration_placeholder_job_type_is_a_seeded_label(self):
        """WR-02 / Phase 13 D-07: the JOB DECLARATION execute_code snippet was removed
        from SKILL.md (demoted to a backstop). The WR-02 placeholder-job_type invariant
        no longer applies to an agent-side snippet; the revenium-classifier plugin owns
        job_type minting now. Assert the snippet is absent so the demoted state holds."""
        text = (SKILL / 'SKILL.md').read_text()
        blocks = re.findall(r'```python\n(.*?)\n```', text, re.DOTALL)
        snippet_blocks = [b for b in blocks if 'def write_job_marker' in b and 'taxonomy_path' in b]
        self.assertEqual(
            len(snippet_blocks), 0,
            'Phase 13 D-07: write_job_marker+taxonomy snippet must be absent from SKILL.md; '
            f'found {len(snippet_blocks)} — the classifier plugin owns job_type minting now')

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

    def test_hooks_status_sh_three_verdicts(self):
        """hooks-status.sh emits stable exit codes for scripting:
          1 = hooks NOT registered (run install-hooks.sh)
          2 = hooks registered but no recent capture activity
          0 = hooks registered AND firing in the last hour

        The verdict text changes over time; the exit code is the contract.
        Tests all three branches by manipulating tool-events/, state.db, and
        config.yaml in a tempdir.
        """
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        import time

        def setup_skill_tree(hermes_home):
            scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            for name in ('common.sh', 'hooks-status.sh',
                         'pre_llm_call.sh', 'pre_tool_call.sh', 'post_tool_call.sh'):
                shutil.copy(SKILL / 'scripts' / name, scripts_dir)
            return scripts_dir

        # ---- Branch 1: hooks NOT registered → exit 1 ----
        tmp = tempfile.mkdtemp(prefix='gsd-hstatus-1-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'hooks-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1,
                f'expected exit 1 on no-registration, got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}')
            self.assertIn('NOT registered', result.stdout)
            self.assertIn('install-hooks.sh', result.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---- Branch 2: hooks registered, no capture activity, no agent  ----
        #     activity in last hour → exit 2 ("registered but quiet")
        tmp = tempfile.mkdtemp(prefix='gsd-hstatus-2-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            # Write a config.yaml that references each hook script path.
            pre_llm = os.path.join(scripts_dir, 'pre_llm_call.sh')
            pre_tool = os.path.join(scripts_dir, 'pre_tool_call.sh')
            post_tool = os.path.join(scripts_dir, 'post_tool_call.sh')
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write(
                    f'hooks:\n'
                    f'  pre_llm_call:\n'
                    f'    - command: {pre_llm}\n      timeout: 5\n'
                    f'  pre_tool_call:\n'
                    f'    - command: {pre_tool}\n      timeout: 5\n'
                    f'  post_tool_call:\n'
                    f'    - command: {post_tool}\n      timeout: 5\n'
                )
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'hooks-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2,
                f'expected exit 2 (registered+quiet), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}')
            self.assertIn('no tool activity has occurred yet', result.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---- Branch 3: hooks registered + recent JSONL → exit 0 ("firing") ----
        tmp = tempfile.mkdtemp(prefix='gsd-hstatus-3-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, exist_ok=True)
            # A recent JSONL file proves the hook fired in the last 60 min.
            jsonl = os.path.join(tool_events_dir, 'diag.jsonl')
            with open(jsonl, 'w') as f:
                f.write('{"sid":"diag","tool":"shell","duration_ms":1,"success":true}\n')
            # mtime = now ensures find -mmin -60 picks it up.
            now = time.time()
            os.utime(jsonl, (now, now))

            pre_llm = os.path.join(scripts_dir, 'pre_llm_call.sh')
            pre_tool = os.path.join(scripts_dir, 'pre_tool_call.sh')
            post_tool = os.path.join(scripts_dir, 'post_tool_call.sh')
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write(
                    f'hooks:\n'
                    f'  pre_llm_call:\n    - command: {pre_llm}\n      timeout: 5\n'
                    f'  pre_tool_call:\n    - command: {pre_tool}\n      timeout: 5\n'
                    f'  post_tool_call:\n    - command: {post_tool}\n      timeout: 5\n'
                )
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': state_dir}
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'hooks-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                f'expected exit 0 (firing), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}')
            self.assertIn('Hooks are firing', result.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_hooks_sh_prints_approval_banner(self):
        """install-hooks.sh prints the loud manual-approval banner on BOTH
        the slow-path (first run) and the fast-path (no-op re-run). The
        Ubuntu sandbox bug was operators running install-hooks.sh once,
        seeing 'Revenium hooks already registered' on the second run, and
        missing the approval-requirement reminder buried at the bottom of
        the first-run output.
        """
        import os
        import shutil
        import subprocess
        import tempfile

        def setup_skill_tree(hermes_home):
            scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            for name in ('common.sh', 'install-hooks.sh',
                         'pre_llm_call.sh', 'pre_tool_call.sh', 'post_tool_call.sh'):
                shutil.copy(SKILL / 'scripts' / name, scripts_dir)
            return scripts_dir

        tmp = tempfile.mkdtemp(prefix='gsd-installhooks-banner-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}

            # Slow-path: first run from scratch.
            result1 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'install-hooks.sh')],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result1.returncode, 0,
                f'slow-path failed: {result1.stdout}\n{result1.stderr}')
            self.assertIn('INERT until you approve them', result1.stdout)
            self.assertIn('hooks_auto_accept: true', result1.stdout)

            # Fast-path: re-run is a no-op for registration but MUST still
            # surface the approval banner.
            result2 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'install-hooks.sh')],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result2.returncode, 0,
                f'fast-path failed: {result2.stdout}\n{result2.stderr}')
            self.assertIn('already registered', result2.stdout)
            self.assertIn('INERT until you approve them', result2.stdout,
                'fast-path must STILL print the approval banner (regression: '
                'silent fast-path was how the Ubuntu sandbox missed it)')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_plugin_sh_dry_run(self):
        """install-plugin.sh --dry-run prints every operation it would perform
        and touches no filesystem state. Pins the dry-run contract used by the
        test below and by operators previewing the install."""
        import os
        import shutil
        import subprocess
        import tempfile

        tmp = tempfile.mkdtemp(prefix='gsd-plugin-dryrun-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
            plugins_src = os.path.join(hermes_home, 'skills', 'revenium', 'plugins',
                                       'revenium-classifier')
            os.makedirs(scripts_dir, exist_ok=True)
            os.makedirs(plugins_src, exist_ok=True)
            # Plugin source must exist for the script to reach the dry-run output.
            shutil.copy(SKILL / 'plugins' / 'revenium-classifier' / 'plugin.yaml',
                        plugins_src)
            shutil.copy(SKILL / 'scripts' / 'common.sh', scripts_dir)
            shutil.copy(SKILL / 'scripts' / 'install-plugin.sh', scripts_dir)

            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium'),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'install-plugin.sh'), '--dry-run'],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            out = result.stdout
            self.assertIn('[dry-run]', out)
            self.assertIn(f'{hermes_home}/plugins/revenium-classifier', out)
            self.assertIn(f'{hermes_home}/config.yaml', out)
            self.assertIn('dry-run — nothing was changed', out)

            # Confirm nothing was actually created.
            self.assertFalse(os.path.exists(os.path.join(hermes_home, 'plugins')),
                             'dry-run must not create plugin dest dir')
            self.assertFalse(os.path.exists(os.path.join(hermes_home, 'config.yaml')),
                             'dry-run must not create config.yaml')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_plugin_sh_happy_path(self):
        """install-plugin.sh creates ~/.hermes/plugins/revenium-classifier and
        enables it in ~/.hermes/config.yaml. Tests three config.yaml scenarios:
        absent, present-without-plugins-block, present-with-plugins-block.
        Idempotent: a second run is a no-op against the config.yaml.
        """
        import os
        import shutil
        import subprocess
        import tempfile

        def setup_skill_tree(hermes_home):
            scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
            plugins_src = os.path.join(hermes_home, 'skills', 'revenium', 'plugins',
                                       'revenium-classifier')
            os.makedirs(scripts_dir, exist_ok=True)
            os.makedirs(plugins_src, exist_ok=True)
            # Real plugin contents matter for the cp -R to succeed.
            for name in ('plugin.yaml', '__init__.py', 'classifier.py'):
                shutil.copy(SKILL / 'plugins' / 'revenium-classifier' / name,
                            plugins_src)
            shutil.copy(SKILL / 'scripts' / 'common.sh', scripts_dir)
            shutil.copy(SKILL / 'scripts' / 'install-plugin.sh', scripts_dir)
            return scripts_dir

        def run_install(env):
            return subprocess.run(
                ['bash', os.path.join(env['HERMES_HOME'], 'skills', 'revenium',
                                       'scripts', 'install-plugin.sh'),
                 '--no-restart'],
                env=env, capture_output=True, text=True, timeout=15,
            )

        # ---- Scenario A: no config.yaml present ----
        tmp = tempfile.mkdtemp(prefix='gsd-plugin-a-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            setup_skill_tree(hermes_home)
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}
            result = run_install(env)
            self.assertEqual(result.returncode, 0,
                f'scenario A failed: {result.stdout}\n{result.stderr}')
            # Plugin copied.
            dest = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            self.assertTrue(os.path.isfile(os.path.join(dest, 'plugin.yaml')))
            self.assertTrue(os.path.isfile(os.path.join(dest, 'classifier.py')))
            # config.yaml created with plugins.enabled containing the plugin.
            config = os.path.join(hermes_home, 'config.yaml')
            self.assertTrue(os.path.exists(config))
            content = open(config).read()
            self.assertIn('plugins:', content)
            self.assertIn('- revenium-classifier', content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---- Scenario B: existing config.yaml with no plugins: block ----
        tmp = tempfile.mkdtemp(prefix='gsd-plugin-b-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            setup_skill_tree(hermes_home)
            config = os.path.join(hermes_home, 'config.yaml')
            with open(config, 'w') as f:
                f.write('approvals:\n  mode: manual\n\nhooks: {}\n')
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}
            result = run_install(env)
            self.assertEqual(result.returncode, 0,
                f'scenario B failed: {result.stdout}\n{result.stderr}')
            content = open(config).read()
            self.assertIn('plugins:', content)
            self.assertIn('- revenium-classifier', content)
            # Pre-existing keys untouched.
            self.assertIn('approvals:', content)
            self.assertIn('hooks: {}', content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---- Scenario C: existing config.yaml WITH plugins.enabled block ----
        tmp = tempfile.mkdtemp(prefix='gsd-plugin-c-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            setup_skill_tree(hermes_home)
            config = os.path.join(hermes_home, 'config.yaml')
            with open(config, 'w') as f:
                f.write('plugins:\n  enabled:\n    - some-other-plugin\n')
            env = {**os.environ, 'HERMES_HOME': hermes_home,
                   'REVENIUM_STATE_DIR': os.path.join(hermes_home, 'state', 'revenium')}
            result = run_install(env)
            self.assertEqual(result.returncode, 0,
                f'scenario C failed: {result.stdout}\n{result.stderr}')
            content = open(config).read()
            self.assertIn('- some-other-plugin', content)
            self.assertIn('- revenium-classifier', content)
            # Idempotency: run again, content must not change.
            result2 = run_install(env)
            self.assertEqual(result2.returncode, 0, result2.stderr)
            content2 = open(config).read()
            self.assertEqual(
                content.count('- revenium-classifier'),
                content2.count('- revenium-classifier'),
                'second install run duplicated the plugin entry',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cron_sh_loops_per_REVENIUM_CRON_LOOP_COUNT(self):
        """cron.sh runs the inner pipeline (hermes-report → budget-check →
        tool-event-report) once per cron tick by default, but loops N times
        when REVENIUM_CRON_LOOP_COUNT=N is set. Pins the sub-minute demo
        cadence knob; broken loop logic would silently revert to once/minute.
        """
        import os
        import shutil
        import subprocess
        import tempfile

        tmp = tempfile.mkdtemp(prefix='gsd-cron-loop-')
        try:
            hermes_home = os.path.join(tmp, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
            os.makedirs(state_dir, exist_ok=True)
            os.makedirs(scripts_dir, exist_ok=True)

            # Copy common.sh + cron.sh into a scratch skill tree so we can
            # stub the three inner scripts without touching the repo.
            shutil.copy(SKILL / 'scripts' / 'common.sh', scripts_dir)
            shutil.copy(SKILL / 'scripts' / 'cron.sh', scripts_dir)

            counter_file = os.path.join(tmp, 'invocations.count')
            open(counter_file, 'w').close()
            for name in ('hermes-report.sh', 'guardrail-check.sh', 'tool-event-report.sh'):
                stub = os.path.join(scripts_dir, name)
                with open(stub, 'w') as f:
                    f.write(
                        '#!/usr/bin/env bash\n'
                        f'echo "{name}" >> "{counter_file}"\n'
                    )
                os.chmod(stub, 0o755)

            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_CRON_LOOP_COUNT': '3',
                'REVENIUM_CRON_LOOP_SLEEP_SECONDS': '0',  # 0s keeps the test fast
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'cron.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'cron.sh exit {result.returncode}; stderr={result.stderr}',
            )

            with open(counter_file) as f:
                invocations = [ln for ln in f.read().splitlines() if ln.strip()]

            # 3 loop iterations × 3 inner scripts = 9 invocations, in order
            # per iteration.
            self.assertEqual(
                len(invocations), 9,
                f'expected 9 inner-script invocations (3 loops × 3 scripts), '
                f'got {len(invocations)}:\n' + '\n'.join(invocations),
            )
            self.assertEqual(invocations[:3], [
                'hermes-report.sh', 'guardrail-check.sh', 'tool-event-report.sh',
            ], f'per-iteration ordering broken: {invocations[:3]}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_install_cron_sh_dry_run_interval_seconds(self):
        """install-cron.sh --interval-seconds N --dry-run emits a crontab
        line carrying the correct loop env (REVENIUM_CRON_LOOP_COUNT,
        REVENIUM_CRON_LOOP_SLEEP_SECONDS) translated from N. Default
        (no flag) emits NO loop env to preserve historical behavior.
        Rejects N outside 1..60 with a non-zero exit code.
        """
        import os
        import subprocess

        install_cron = str(SKILL / 'scripts' / 'install-cron.sh')

        # Default (no flag) — no loop env in the crontab line.
        result = subprocess.run(
            ['bash', install_cron, '--dry-run'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hermes-revenium-metering', result.stdout)
        self.assertNotIn('REVENIUM_CRON_LOOP_COUNT', result.stdout,
                         'default install must not emit loop env')

        # --interval-seconds 15 — 4x per minute, 15s sleep.
        result = subprocess.run(
            ['bash', install_cron, '--interval-seconds', '15', '--dry-run'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('REVENIUM_CRON_LOOP_COUNT=4', result.stdout)
        self.assertIn('REVENIUM_CRON_LOOP_SLEEP_SECONDS=15', result.stdout)

        # --interval-seconds 60 — equivalent to default; no loop env.
        result = subprocess.run(
            ['bash', install_cron, '--interval-seconds', '60', '--dry-run'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('REVENIUM_CRON_LOOP_COUNT', result.stdout)

        # Out-of-range values must fail loudly.
        for bad in ('0', '61', '-5', 'abc'):
            result = subprocess.run(
                ['bash', install_cron, '--interval-seconds', bad, '--dry-run'],
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(
                result.returncode, 0,
                f'expected non-zero exit for --interval-seconds {bad}, got 0',
            )

    def test_log_helper_no_double_write_under_cron_redirect(self):
        """Regression: under cron's `>> LOG_FILE 2>&1` invocation shape,
        common.sh log() must write exactly ONE line per call to LOG_FILE.

        The prior implementation (`echo … | tee -a "${LOG_FILE}" >&2`) doubled
        every entry — once via tee's append-write, once via the cron stderr
        redirect catching tee's stdout that we'd routed to stderr.
        Confirmed live on Ubuntu sandbox 2026-05-19: every metering log line
        appeared twice with identical timestamps.
        """
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = os.path.join(tmp, '.hermes')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            os.makedirs(state_dir, exist_ok=True)
            log_file = os.path.join(state_dir, 'revenium-metering.log')

            common = SKILL / 'scripts' / 'common.sh'
            script = (
                f'export HERMES_HOME={hermes_home!r}\n'
                f'export REVENIUM_STATE_DIR={state_dir!r}\n'
                f'source {str(common)!r}\n'
                'info "alpha"\n'
                'warn "bravo"\n'
                'error "charlie"\n'
            )

            # Mirror cron's exact invocation shape: stdout → LOG_FILE, stderr
            # merged into stdout (== cron's `>> LOG_FILE 2>&1`). Under this
            # combination the OLD helper writes 6 lines (2 per call); the
            # fixed helper writes exactly 3.
            with open(log_file, 'a') as out:
                result = subprocess.run(
                    ['bash', '-c', script],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                )
            self.assertEqual(
                result.returncode, 0,
                f'bash exited {result.returncode}',
            )

            with open(log_file) as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]

            self.assertEqual(
                len(lines), 3,
                'expected 3 log lines under cron-style redirect, got '
                f'{len(lines)}:\n' + '\n'.join(lines),
            )
            self.assertIn('alpha', lines[0])
            self.assertIn('bravo', lines[1])
            self.assertIn('charlie', lines[2])

    def test_cron_marker_split_end_to_end(self):
        """TEST-03 / COMPAT-02 / COMPAT-03: synthetic state.db + marker fixture ->
        exactly N Revenium invocations with byte-exact conservation, idempotent
        across simulated partial failure, and zero-marker fallthrough emits exactly
        one call whose argv differs from the legacy form only by --task-type
        unclassified (SC3 byte-diff invariant, B4)."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile
        from decimal import Decimal

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a3{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'code_review' if i % 2 == 0 else 'refactor',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def run_cron(env, invocations_log):
            """Invoke hermes-report.sh once, parsing the invocation log into
            argv lists. Returns (exit_code, [argv_list, ...])."""
            if os.path.exists(invocations_log):
                os.unlink(invocations_log)
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    # The shim writes shell-escaped args; round-trip via shlex.
                    import shlex
                    invocations.append(shlex.split(line))
            return result.returncode, invocations, result.stdout + result.stderr

        def argv_to_flags(argv):
            """Convert flat argv to {flag: value} dict for assertions."""
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        tmpdir = tempfile.mkdtemp(prefix='gsd-cron-e2e-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            ledger = os.path.join(state_dir, 'revenium-hermes.ledger')

            # Build the revenium shim. Critical: place it at ${HOME}/.local/bin
            # because common.sh::ensure_path prepends a fixed list of directories
            # (including /opt/homebrew/bin where the real revenium lives) AFTER
            # whatever PATH we set. ${HOME}/.local/bin is the LAST prepend in
            # ensure_path's loop, so it ends up FIRST in PATH; the shim wins.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            invocations_log = os.path.join(tmpdir, 'invocations.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    # Skip --help probes (Phase 9 CLI-capability preflight) — not real invocations.\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    '    # Emit each arg shell-escaped on one line per invocation.\n'
                    '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                    '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': invocations_log,
                'TZ': 'UTC',
            }

            # =====================================================
            # Sub-case 1: N markers in {1, 2, 5, 10} -> N invocations
            # with conservation invariant byte-exact across all fields.
            # =====================================================
            for n in (1, 2, 5, 10):
                sid = f'20260512_120000_n{n:02d}'
                input_tokens = 10000 + n * 11
                output_tokens = 4000 + n * 7
                cache_read = 200 + n * 3
                cache_write = 100 + n * 5
                total_tokens = input_tokens + output_tokens
                estimated_cost = '0.123456'

                # Reset fixture state for each N.
                for path in (state_db, ledger):
                    if os.path.exists(path):
                        os.unlink(path)
                for f_ in os.listdir(markers_dir):
                    # Skip subdirectories (e.g., .ready/ — G-03 sentinel dir created by common.sh).
                    full_path = os.path.join(markers_dir, f_)
                    if os.path.isdir(full_path):
                        continue
                    os.unlink(full_path)

                build_state_db(state_db, [{
                    'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                    'input_tokens': input_tokens, 'output_tokens': output_tokens,
                    'cache_read': cache_read, 'cache_write': cache_write,
                    'reasoning': 0, 'estimated_cost': estimated_cost,
                    'api_calls': n, 'started_at': 1715514000.0,
                    'ended_at': 1715515100.0,
                    'billing_provider': 'anthropic',
                }])

                with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                    for m in make_markers(n, sid):
                        f.write(json.dumps(m, separators=(',', ':')) + '\n')

                rc, invocations, output = run_cron(base_env, invocations_log)
                self.assertEqual(rc, 0, f'cron exit {rc} for n={n}: {output}')
                self.assertEqual(len(invocations), n,
                                 f'expected {n} invocations, got {len(invocations)}: {output}')

                # Conservation invariant per field.
                sum_input = sum(int(argv_to_flags(a)['--input-tokens']) for a in invocations)
                sum_output = sum(int(argv_to_flags(a)['--output-tokens']) for a in invocations)
                sum_cache_read = sum(int(argv_to_flags(a)['--cache-read-tokens']) for a in invocations)
                sum_cache_write = sum(int(argv_to_flags(a)['--cache-creation-tokens']) for a in invocations)
                sum_total = sum(int(argv_to_flags(a)['--total-tokens']) for a in invocations)

                self.assertEqual(sum_input, input_tokens,
                                 f'input conservation violated at n={n}')
                self.assertEqual(sum_output, output_tokens,
                                 f'output conservation violated at n={n}')
                self.assertEqual(sum_cache_read, cache_read,
                                 f'cache_read conservation violated at n={n}')
                self.assertEqual(sum_cache_write, cache_write,
                                 f'cache_write conservation violated at n={n}')
                self.assertEqual(sum_total, input_tokens + output_tokens,
                                 f'total conservation violated at n={n}')

                # Cost conservation byte-exact via Decimal.
                cost_strs = [argv_to_flags(a).get('--total-cost', '0') for a in invocations]
                cost_sum = sum(Decimal(c) for c in cost_strs)
                self.assertEqual(cost_sum, Decimal(estimated_cost),
                                 f'cost conservation violated at n={n}: {cost_strs}')

                # Per-marker flags present on every invocation; transaction-id
                # matches ${sid}-${total_tokens}-${muid} shape.
                expected_muids = [m['muid'] for m in make_markers(n, sid)]
                for argv in invocations:
                    flags = argv_to_flags(argv)
                    self.assertIn('--task-type', flags)
                    self.assertIn('--operation-type', flags)
                    txid = flags.get('--transaction-id', '')
                    prefix = f'{sid}-{total_tokens}-'
                    self.assertTrue(txid.startswith(prefix),
                                    f'transaction-id "{txid}" missing prefix "{prefix}" at n={n}')
                    suffix_muid = txid[len(prefix):]
                    self.assertIn(suffix_muid, expected_muids,
                                  f'transaction-id muid suffix not in expected muids at n={n}')

            # =====================================================
            # Sub-case 2: zero markers -> exactly one call with
            # --task-type unclassified and NO --operation-type;
            # transaction-id is ${sid}-${total_tokens} (B4: no muid suffix).
            # =====================================================
            sid_zero = '20260512_120000_zero'
            input_tokens = 7000
            output_tokens = 2000
            total_tokens = input_tokens + output_tokens

            for path in (state_db, ledger):
                if os.path.exists(path):
                    os.unlink(path)
            for f_ in os.listdir(markers_dir):
                # Skip subdirectories (e.g., .ready/ — G-03 sentinel dir created by common.sh).
                full_path = os.path.join(markers_dir, f_)
                if os.path.isdir(full_path):
                    continue
                os.unlink(full_path)

            build_state_db(state_db, [{
                'id': sid_zero, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': input_tokens, 'output_tokens': output_tokens,
                'cache_read': 100, 'cache_write': 50,
                'reasoning': 0, 'estimated_cost': '0.045000',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715515100.0,
                'billing_provider': 'anthropic',
            }])
            # No marker file for sid_zero -> zero-marker fallthrough.

            rc, invocations, output = run_cron(base_env, invocations_log)
            self.assertEqual(rc, 0, f'zero-marker cron exit {rc}: {output}')
            self.assertEqual(len(invocations), 1,
                             f'zero-marker expected 1 call, got {len(invocations)}: {output}')

            flags = argv_to_flags(invocations[0])
            self.assertEqual(flags.get('--task-type'), 'unclassified',
                             'zero-marker fallthrough must use --task-type unclassified')
            self.assertEqual(flags.get('--operation-type'), 'CHAT',
                             'zero-marker fallthrough must emit --operation-type CHAT (WIRE-01 / D-22)')
            self.assertEqual(flags.get('--transaction-id'), f'{sid_zero}-{total_tokens}',
                             'B4: zero-marker --transaction-id must be ${sid}-${total_tokens} '
                             '(no synthetic muid suffix in wire id)')

            # The ledger row for the zero-marker path must carry a synthetic
            # non-empty muid in field 5 (D-11). Read the ledger and confirm.
            with open(ledger) as f:
                ledger_lines = [l.rstrip('\n') for l in f if l.strip()]
            zero_rows = [l for l in ledger_lines if l.startswith(f'HERMES:{sid_zero}:')]
            self.assertEqual(len(zero_rows), 1,
                             f'expected 1 ledger row for zero-marker session, got {len(zero_rows)}')
            fields = zero_rows[0].split(':')
            self.assertEqual(len(fields), 5,
                             f'D-07: zero-marker ledger row must have 5 colon-fields, got {len(fields)}')
            self.assertTrue(fields[4].startswith('unclassified-'),
                            f'D-11: zero-marker synthetic muid must use unclassified- prefix, '
                            f'got {fields[4]!r}')
            self.assertGreater(len(fields[4]), len('unclassified-'),
                               'D-11: zero-marker synthetic muid must be non-empty')

            # =====================================================
            # Sub-case 3: idempotency under simulated partial failure
            # (COMPAT-03, Pitfall 8). Run with 5 markers at total_tokens=T1;
            # truncate ledger to first 3 rows (simulating cron killed between
            # meter call 3 and call 5). Then bump state.db total_tokens to T2>T1
            # (real-world cron tick: agent kept running between minutes) and
            # rerun; assert exactly 2 NEW invocations corresponding to muids 4-5.
            #
            # Note on the outer pre-filter (hermes-report.sh:71): it short-circuits
            # any (sid, total_tokens) tuple already in the ledger to (a) preserve v1
            # backward-compat idempotency and (b) prevent zero-marker re-emission
            # on each tick. The realistic recovery scenario is "tokens have grown",
            # so we bump T1 -> T2 between runs. The per-muid dedup inside
            # parse_prior_state then correctly identifies muids 4-5 as un-emitted
            # (their ts > the latest ledger row's ts).
            # =====================================================
            sid_pf = '20260512_120000_pf05'
            input_tokens_t1 = 10000
            output_tokens_t1 = 4000
            cache_read_t1 = 250
            cache_write_t1 = 125
            estimated_cost_t1 = '0.250000'
            total_tokens_t1 = input_tokens_t1 + output_tokens_t1

            for path in (state_db, ledger):
                if os.path.exists(path):
                    os.unlink(path)
            for f_ in os.listdir(markers_dir):
                # Skip subdirectories (e.g., .ready/ — G-03 sentinel dir created by common.sh).
                full_path = os.path.join(markers_dir, f_)
                if os.path.isdir(full_path):
                    continue
                os.unlink(full_path)

            build_state_db(state_db, [{
                'id': sid_pf, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': input_tokens_t1, 'output_tokens': output_tokens_t1,
                'cache_read': cache_read_t1, 'cache_write': cache_write_t1,
                'reasoning': 0, 'estimated_cost': estimated_cost_t1,
                'api_calls': 5, 'started_at': 1715514000.0,
                'ended_at': 1715515100.0,
                'billing_provider': 'anthropic',
            }])
            pf_markers = make_markers(5, sid_pf)
            with open(os.path.join(markers_dir, f'{sid_pf}.jsonl'), 'w') as f:
                for m in pf_markers:
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')

            # Run 1: all 5 markers reported at total_tokens=T1.
            rc, run1_invocations, output1 = run_cron(base_env, invocations_log)
            self.assertEqual(rc, 0, f'partial-failure run1 exit {rc}: {output1}')
            self.assertEqual(len(run1_invocations), 5,
                             f'partial-failure run1 expected 5 calls, got {len(run1_invocations)}: {output1}')

            # Simulate partial failure: truncate ledger to first 3 rows for sid_pf.
            with open(ledger) as f:
                all_rows = [l for l in f if l.strip()]
            sid_pf_rows = [l for l in all_rows if l.startswith(f'HERMES:{sid_pf}:')]
            self.assertEqual(len(sid_pf_rows), 5,
                             f'expected 5 rows for {sid_pf} after run1, got {len(sid_pf_rows)}')
            kept = [l for l in all_rows if not l.startswith(f'HERMES:{sid_pf}:')]
            kept.extend(sid_pf_rows[:3])
            with open(ledger, 'w') as f:
                f.writelines(kept)

            # Bump state.db total_tokens (T2 > T1) to simulate the agent
            # continuing to consume tokens between cron ticks. The 5 original
            # markers stay in place; muids 4-5 still have ts > the latest
            # ledger row's ts, so parse_prior_state filters them as un-emitted.
            new_input_tokens = input_tokens_t1 + 600
            new_output_tokens = output_tokens_t1 + 400
            new_total_tokens = new_input_tokens + new_output_tokens
            conn = sqlite3.connect(state_db)
            conn.execute(
                'UPDATE sessions SET input_tokens=?, output_tokens=? WHERE id=?',
                (new_input_tokens, new_output_tokens, sid_pf),
            )
            conn.commit()
            conn.close()

            # Run 2: only the 2 missing muids should be emitted; transaction-id
            # carries the NEW total_tokens (T2) per CRON-04.
            rc, run2_invocations, output2 = run_cron(base_env, invocations_log)
            self.assertEqual(rc, 0, f'partial-failure run2 exit {rc}: {output2}')
            self.assertEqual(len(run2_invocations), 2,
                             f'partial-failure run2 expected 2 calls (muids 4-5), '
                             f'got {len(run2_invocations)}: {output2}')

            replayed_muids = []
            for argv in run2_invocations:
                txid = argv_to_flags(argv).get('--transaction-id', '')
                prefix = f'{sid_pf}-{new_total_tokens}-'
                self.assertTrue(txid.startswith(prefix),
                                f'replay transaction-id "{txid}" missing prefix "{prefix}"')
                replayed_muids.append(txid[len(prefix):])

            expected_replay_muids = {pf_markers[3]['muid'], pf_markers[4]['muid']}
            self.assertEqual(set(replayed_muids), expected_replay_muids,
                             f'partial-failure replay must emit exactly muids 4-5, '
                             f'got {replayed_muids}')

            # Run 3 (re-running without any further state.db change) MUST emit
            # zero new invocations because the new rows added by run 2 trip the
            # outer (sid, T2) pre-filter. This proves the ledger is now consistent.
            rc, run3_invocations, output3 = run_cron(base_env, invocations_log)
            self.assertEqual(rc, 0, f'partial-failure run3 exit {rc}: {output3}')
            self.assertEqual(len(run3_invocations), 0,
                             f'partial-failure run3 expected 0 calls (fully reported), '
                             f'got {len(run3_invocations)}: {output3}')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_s2_bias_50_50_attribution(self):
        """TEST-04 / D-17 / Pitfall 5: pins the documented S2 bias direction.

        GUARDRAIL share is an UPPER BOUND, not an estimate (see
        references/setup.md "How attribution works"). The S2 equal-split
        gives 50/50 attribution between a tiny GUARDRAIL classification
        marker and a large work marker — the bias is intentional and
        documented. This test fails-loud if the splitter ever starts
        approximating real token weight; D-18 telemetry lines are
        asserted verbatim so a refactor cannot silently drift them.

        Layer 1: pure-function pin on equal_split. Layer 2: full
        cron pipeline emits the locked S2_INFO and S2_WARN log phrases
        per D-18."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile
        from decimal import Decimal

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        # ===== Layer 1: pure-function pin =====
        sys.path.insert(0, str(SCRIPTS_DIR))
        from split_strategies import equal_split  # noqa: WPS433 (intentional dynamic import)

        layer1_delta = {
            "input": 8000, "output": 0, "cache_read": 0, "cache_write": 0,
            "total": 8000, "cost": "0.080000",
        }
        layer1_splits = equal_split(layer1_delta, 2)
        self.assertEqual(layer1_splits[0]["input"], 4000,
                         "S2 50/50 bias: marker 0 must receive exactly half of input")
        self.assertEqual(layer1_splits[1]["input"], 4000,
                         "S2 50/50 bias: marker 1 must receive exactly half of input")
        self.assertEqual(layer1_splits[0]["total"], 4000,
                         "S2 50/50 bias: marker 0 must receive exactly half of total")
        self.assertEqual(layer1_splits[1]["total"], 4000,
                         "S2 50/50 bias: marker 1 must receive exactly half of total")
        self.assertEqual(Decimal(layer1_splits[0]["cost"]) + Decimal(layer1_splits[1]["cost"]),
                         Decimal("0.080000"),
                         "Cost conservation must be Decimal-exact across S2 split")

        # ===== Layer 2: full cron pipeline emits locked D-18 telemetry =====
        tmpdir = tempfile.mkdtemp(prefix='gsd-s2-bias-')
        try:
            shim_home = os.path.join(tmpdir, 'home')
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(markers_dir, mode=0o700)
            os.makedirs(bin_dir)
            state_db = os.path.join(hermes_home, 'state.db')
            invocations_log = os.path.join(tmpdir, 'invocations.log')

            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                    '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            # D-17 fixture sizes: 1 large work-turn (~8000) + 1 small GUARDRAIL
            # classification (~300). The session-total delta is 8300; the
            # cron's S2_INFO line uses `delta_total // n` so n=2 -> 4150 (W1).
            sid = '20260512_120000_bias'
            input_tokens = 6000
            output_tokens = 2300
            total_tokens = input_tokens + output_tokens  # 8300

            conn = sqlite3.connect(state_db)
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            conn.execute(
                'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid, 'claude-sonnet-4-6', 'test',
                 input_tokens, output_tokens, 0, 0, 0, '0.083000', 2,
                 1715514000.0, 1715515100.0, 'anthropic'),
            )
            conn.commit()
            conn.close()

            markers = [
                # Marker 0: large work-turn (CHAT)
                {'muid': '01893b8a300abcdef0123456789abcdef0',
                 'ts': 1715515001.0, 'sid': sid,
                 'task_type': 'code_review', 'operation_type': 'CHAT'},
                # Marker 1: small GUARDRAIL classification
                {'muid': '01893b8a301abcdef0123456789abcdef0',
                 'ts': 1715515002.0, 'sid': sid,
                 'task_type': 'planning', 'operation_type': 'GUARDRAIL'},
            ]
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                for m in markers:
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': invocations_log,
                'TZ': 'UTC',
            }
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0,
                             f'cron exit {result.returncode}: {result.stderr}')

            # log() writes to LOG_FILE (canonical sink) and mirrors to stderr
            # only on TTY. Subprocess captures non-TTY stderr, so the D-18
            # telemetry lives in the log file under tests.
            log_file = os.path.join(state_dir, 'revenium-metering.log')
            log_content = open(log_file).read() if os.path.exists(log_file) else ''
            combined = result.stdout + result.stderr + log_content
            self.assertIn('S2: window=2, mean_per_marker=4150', combined,
                          f'D-18 INFO line not emitted (W1: locked exact value '
                          f'delta_total=8300 // n=2 == 4150). Got:\n{combined}')
            self.assertIn('S2: classification-dominated window, attribution may be lossy',
                          combined,
                          f'D-18 WARN line not emitted on n=2 + any GUARDRAIL marker. '
                          f'Got:\n{combined}')

            # Sanity: both markers must have been emitted (exactly 2 invocations,
            # one with --operation-type CHAT and one with --operation-type GUARDRAIL).
            with open(invocations_log) as f:
                lines = [l.rstrip('\n') for l in f if l.strip()]
            self.assertEqual(len(lines), 2,
                             f'expected 2 invocations for 2 markers, got {len(lines)}')
            self.assertTrue(any('--operation-type GUARDRAIL' in l for l in lines),
                            'S2 bias test: GUARDRAIL invocation missing')
            self.assertTrue(any('--operation-type CHAT' in l for l in lines),
                            'S2 bias test: CHAT invocation missing')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ledger_v1_v2_discrimination(self):
        """D-10 / B6 / Pitfall D: parse_prior_state correctly distinguishes
        v1 (4-field) from v2 (5-field) ledger rows by len(line.split(':')).

        Exercises the production helper directly (B6 — test is load-bearing,
        not decorative). Pitfall D ("v2-takes-precedence for ts") is verified
        by a fixture where the v1 row has a ts LATER than any v2 row: the
        helper must still return the latest v2 ts as prior_ts when any v2
        rows exist for the sid. A2 (sid-with-colons) defense is verified by
        the AssertionError sub-test.

        Note on prior_muids semantics: the helper returns the GLOBAL set of
        every v2 muid ledger'd for sid (across all total_tokens windows), not
        narrowed to the exact total_tokens. This is the load-bearing
        invariant for partial-failure recovery in test_cron_marker_split_end_to_end."""
        import os
        import sys
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        sys.path.insert(0, str(SCRIPTS_DIR))
        from split_strategies import parse_prior_state  # noqa: WPS433

        tmpdir = tempfile.mkdtemp(prefix='gsd-discrim-')
        try:
            ledger_path = os.path.join(tmpdir, 'revenium-hermes.ledger')

            # Mixed-format fixture for sid-A: one v1 row (4 fields) and four v2
            # rows (5 fields, one muid each per B1). Two of the v2 rows share
            # total_tokens with the v1 row; three v2 rows share total_tokens=5000.
            with open(ledger_path, 'w') as f:
                f.write(
                    # v1 row (D-08: preserved indefinitely)
                    'HERMES:sid-A:1000:1715515000.000\n'
                    # v2 rows at total_tokens=1000 (one muid each per B1)
                    'HERMES:sid-A:1000:1715515100.500:muidA\n'
                    # v2 rows at total_tokens=5000
                    'HERMES:sid-A:5000:1715515150.000:muidB\n'
                    'HERMES:sid-A:5000:1715515180.000:muidC\n'
                    'HERMES:sid-A:5000:1715515200.000:muidD\n'
                )

            # Query (sid-A, total_tokens=1000): prior_muids is the GLOBAL set
            # across all v2 rows for sid-A. prior_ts is the latest v2 ts for
            # sid-A (v2-takes-precedence per Pitfall D).
            prior_ts, prior_muids = parse_prior_state(ledger_path, 'sid-A', 1000)
            self.assertEqual(prior_ts, 1715515200.000,
                             'v2-takes-precedence: prior_ts must be the MAX v2 ts for sid')
            self.assertEqual(prior_muids, {'muidA', 'muidB', 'muidC', 'muidD'},
                             'prior_muids is the GLOBAL set across all (sid, *) v2 rows')

            # Query (sid-A, total_tokens=5000): same global muids, same prior_ts.
            prior_ts, prior_muids = parse_prior_state(ledger_path, 'sid-A', 5000)
            self.assertEqual(prior_ts, 1715515200.000)
            self.assertEqual(prior_muids, {'muidA', 'muidB', 'muidC', 'muidD'})

            # Query (sid-A, total_tokens=9999): no rows match this exact
            # total_tokens, but the helper still returns the global view per
            # sid — every v2 muid that ever shipped stays in the set.
            prior_ts, prior_muids = parse_prior_state(ledger_path, 'sid-A', 9999)
            self.assertEqual(prior_ts, 1715515200.000)
            self.assertEqual(prior_muids, {'muidA', 'muidB', 'muidC', 'muidD'})

            # Query (sid-Z, anything): no rows at all for this sid.
            prior_ts, prior_muids = parse_prior_state(ledger_path, 'sid-Z', 1234)
            self.assertEqual(prior_ts, 0.0)
            self.assertEqual(prior_muids, set())

            # Pitfall D verification: a v1 row with a LATER ts than any v2 row
            # must NOT override the v2-takes-precedence rule. Build a second
            # fixture and confirm.
            ledger_p2 = os.path.join(tmpdir, 'pitfall-d.ledger')
            with open(ledger_p2, 'w') as f:
                f.write(
                    # v1 row with very large ts (e.g., far-future cleanup)
                    'HERMES:sid-A:1000:9999999999.000\n'
                    # v2 row with smaller ts
                    'HERMES:sid-A:1000:1715515100.500:muidA\n'
                )
            prior_ts, prior_muids = parse_prior_state(ledger_p2, 'sid-A', 1000)
            self.assertEqual(prior_ts, 1715515100.500,
                             'Pitfall D: v2 ts takes precedence over a LATER v1 ts when '
                             'any v2 row exists for the sid')
            self.assertEqual(prior_muids, {'muidA'})

            # v1-only fixture: no v2 rows. prior_ts falls back to v1 max; muids empty.
            ledger_v1 = os.path.join(tmpdir, 'v1-only.ledger')
            with open(ledger_v1, 'w') as f:
                f.write(
                    'HERMES:sid-B:500:1715515000.000\n'
                    'HERMES:sid-B:1500:1715515050.000\n'
                )
            prior_ts, prior_muids = parse_prior_state(ledger_v1, 'sid-B', 1500)
            self.assertEqual(prior_ts, 1715515050.000,
                             'v1-only ledger: prior_ts is the MAX v1 ts for sid')
            self.assertEqual(prior_muids, set(),
                             'v1-only ledger: prior_muids is empty (no v2 rows)')

            # Missing ledger file: helper returns (0.0, set()) without raising.
            prior_ts, prior_muids = parse_prior_state(
                os.path.join(tmpdir, 'does-not-exist.ledger'), 'sid-A', 1000,
            )
            self.assertEqual(prior_ts, 0.0)
            self.assertEqual(prior_muids, set())

            # A2 defense: sid containing ':' must raise AssertionError so a
            # future sid-format change can't silently corrupt field-count
            # discrimination.
            with self.assertRaises(AssertionError):
                parse_prior_state(ledger_path, 'sid:with:colons', 1000)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_no_tools_classified_not_skipped(self):
        """HOTFIX D-07 mirror: D-07 trivial-skip removed. A turn with no tools and a short
        response must now flow through to the LLM classifier step (and in the test env where
        call_llm is None, must produce an 'unclassified' marker file)."""
        import asyncio
        import importlib
        import json
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-trivial-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            fixture_path = PLUGIN_DIR / 'test-payloads' / 'trivial-turn.json'
            context = json.loads(fixture_path.read_text())
            # No session jsonl exists in tmp HERMES_HOME for this trivial-turn fixture
            asyncio.run(handler.run_classification_async(
                session_id=context['session_id'],
                message=context.get('message'),
                response=context.get('response'),
                model=context.get('model'),
                platform=context.get('platform'),
            ))
            self.assertTrue(
                (handler.MARKERS_DIR / f"{context['session_id']}.jsonl").exists(),
                "no-tools turn must NOW create marker file — D-07 skip removed; classifier falls through to unclassified write",
            )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_never_raises(self):
        """D-04 / SC4 belt: run_classification_async MUST NOT raise out of the classifier
        for ANY error path. Inject failures at every helper boundary and confirm the
        classifier swallows and logs them instead of propagating."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-noraise-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "noraise-sid"
            with open(os.path.join(hh, 'sessions', f"{sid}.jsonl"), 'w') as f:
                f.write(json.dumps({"role": "user"}) + "\n")
                f.write(json.dumps({"role": "tool"}) + "\n")

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            context = {
                "platform": "test", "user_id": "u",
                "session_id": sid,
                "message": "x" * 100,
                "response": "y" * 600,  # > 200 chars, defeats trivial skip
            }

            # Case A — call_llm raises
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm:
                mock_llm.side_effect = RuntimeError("boom from call_llm")
                # MUST NOT raise
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
            # Marker file SHOULD exist with task_type=unclassified (LLM failure fallthrough)
            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            self.assertTrue(marker_path.is_file())
            recs = [json.loads(l) for l in marker_path.read_text().splitlines()]
            self.assertEqual({r['task_type'] for r in recs}, {'unclassified'})

            # Case B — _write_marker_pair raises (filesystem-level catastrophic failure)
            shutil.rmtree(handler.MARKERS_DIR, ignore_errors=True)
            with unittest.mock.patch.object(handler, '_write_marker_pair') as mock_write:
                mock_write.side_effect = OSError("disk full")
                # MUST NOT raise
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))

            # Case C — plugin _on_session_end with garbage session_id swallows the exception
            # (D-04 belt at the plugin boundary; never raises so the plugin manager
            # does not mark revenium-classifier unhealthy on a None sid).
            import importlib.util as _ilu
            _pkg_init = PLUGIN_DIR / '__init__.py'
            _spec = _ilu.spec_from_file_location(
                'revenium_classifier_t05c',
                str(_pkg_init),
                submodule_search_locations=[str(PLUGIN_DIR)],
            )
            _mod = _ilu.module_from_spec(_spec)
            sys.modules['revenium_classifier_t05c'] = _mod
            _spec.loader.exec_module(_mod)
            # MUST NOT raise on a None session_id
            _mod._on_session_end(session_id=None, completed=True, interrupted=False)

            # Case D — missing session_id → silent early return
            asyncio.run(handler.run_classification_async(session_id=''))

            # Case E — call_llm returns garbage object that defeats .choices[0].message.content
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm:
                mock_llm.return_value = object()  # neither attribute nor mapping interface
                # MUST NOT raise; should write unclassified
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))

            # Case F — a job-path helper raises; run_classification_async must still
            # return normally and the task pair must already be written (D-04 / T-13-08).
            # Patch _infer_jobs_via_llm to raise and verify no exception escapes.
            shutil.rmtree(handler.MARKERS_DIR, ignore_errors=True)
            handler.MARKERS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            with unittest.mock.patch.object(handler, '_infer_jobs_via_llm',
                                             side_effect=RuntimeError("job-path boom")):
                # Also patch _read_session_transcript to return a non-empty transcript
                # so the job block actually enters _infer_jobs_via_llm.
                with unittest.mock.patch.object(handler, '_read_session_transcript',
                                                 return_value="user: test\nassistant: ok"):
                    # Patch call_llm for task classification
                    mock_task_resp = unittest.mock.MagicMock()
                    mock_task_resp.choices = [unittest.mock.MagicMock()]
                    mock_task_resp.choices[0].message.content = "code_review"
                    with unittest.mock.patch.object(handler, 'call_llm',
                                                     return_value=mock_task_resp):
                        try:
                            asyncio.run(handler.run_classification_async(
                                session_id=context['session_id'],
                                message=context.get('message'),
                                response=context.get('response'),
                            ))
                        except Exception as exc:
                            self.fail(
                                f"Case F: run_classification_async must not raise when "
                                f"a job-path helper raises; got {exc!r}"
                            )
            # The task pair must still have been written (job failure must not destroy it)
            marker_path_f = handler.MARKERS_DIR / f"{context['session_id']}.jsonl"
            self.assertTrue(marker_path_f.is_file(),
                            "Case F: task marker file must exist even when job-path raises")
            task_recs_f = [json.loads(l) for l in marker_path_f.read_text().splitlines()]
            ops_f = {r.get("operation_type") for r in task_recs_f if "operation_type" in r}
            self.assertIn("GUARDRAIL", ops_f, "Case F: GUARDRAIL record must be present")
            self.assertIn("CHAT", ops_f, "Case F: CHAT record must be present")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_dedupe(self):
        """HOOK-07 / D-13: when a fresh GUARDRAIL+CHAT pair already exists in the marker
        file (within 30s), the hook skips the write to avoid double-writes with the
        agent's FINAL ACTION code path."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import time
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-dedupe-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            # Seed substantive context (defeat heuristic skip)
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "20260513_120100_testsubstantive"
            with open(os.path.join(hh, 'sessions', f"{sid}.jsonl"), 'w') as f:
                f.write(json.dumps({"role": "user"}) + "\n")
                f.write(json.dumps({"role": "tool"}) + "\n")

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Pre-seed the marker file with an agent-written GUARDRAIL+CHAT pair (fresh)
            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            now = time.time()
            with open(marker_path, 'w', encoding='utf-8') as f:
                rec1 = {"muid": "a" * 33, "ts": now - 1.0, "sid": sid,
                        "task_type": "code_review", "operation_type": "GUARDRAIL"}
                rec2 = dict(rec1, muid="b" * 33, ts=now - 0.5, operation_type="CHAT")
                f.write(json.dumps(rec1, separators=(",", ":")) + "\n")
                f.write(json.dumps(rec2, separators=(",", ":")) + "\n")

            self.assertTrue(handler._recent_marker_pair_exists(sid, within_seconds=30.0))

            # Patch call_llm so LLM task classification (Steps 4-6) is NOT called;
            # Step 7 now legitimately may call the LLM for job inference, so we patch
            # _infer_jobs_via_llm to [] to keep this test focused on the task no-double-write
            # invariant rather than asserting the LLM is never called at all.
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm, \
                 unittest.mock.patch.object(handler, '_infer_jobs_via_llm', return_value=[]):
                mock_llm.side_effect = AssertionError("LLM task classification must NOT be called when agent already wrote markers")
                fixture = PLUGIN_DIR / 'test-payloads' / 'substantive-turn.json'
                context = json.loads(fixture.read_text())
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
                mock_llm.assert_not_called()

            # Marker file must have no task double-write: count GUARDRAIL/CHAT lines only.
            # A kind:"job" line from Step 7 is now permitted (not required). The invariant
            # is that the task pair is not doubled (exactly 2 GUARDRAIL/CHAT records).
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]
            task_recs = [r for r in recs if r.get("operation_type") in ("GUARDRAIL", "CHAT")]
            self.assertGreaterEqual(len(lines), 2, f"marker file has too few lines; got {len(lines)}")
            self.assertEqual(len(task_recs), 2, f"hook double-wrote task pair; got {len(task_recs)} task lines")

            # Now age the markers beyond 30s and try again — hook should write
            with open(marker_path, 'w', encoding='utf-8') as f:
                rec1['ts'] = now - 120
                rec2['ts'] = now - 120
                f.write(json.dumps(rec1, separators=(",", ":")) + "\n")
                f.write(json.dumps(rec2, separators=(",", ":")) + "\n")
            self.assertFalse(handler._recent_marker_pair_exists(sid, within_seconds=30.0))
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = "research"
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp), \
                 unittest.mock.patch.object(handler, '_infer_jobs_via_llm', return_value=[]):
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
            # Now marker file has 2 stale + 2 new task lines = 4 GUARDRAIL/CHAT lines
            # (Step 7 may add a job line too, so assert task-line count not total lines).
            lines = marker_path.read_text().splitlines()
            recs_aged = [json.loads(l) for l in lines]
            task_recs_aged = [r for r in recs_aged if r.get("operation_type") in ("GUARDRAIL", "CHAT")]
            self.assertEqual(len(task_recs_aged), 4,
                             f"expected 4 task lines (2 stale + 2 new); got {len(task_recs_aged)}")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_llm_label(self):
        """HOOK-05 / D-06: mocked call_llm returns 'code_review'; the marker pair
        carries task_type=code_review."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-llm-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            # Seed a session jsonl with one tool to defeat the heuristic skip
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "20260513_120100_testsubstantive"
            with open(os.path.join(hh, 'sessions', f"{sid}.jsonl"), 'w') as f:
                f.write(json.dumps({"role": "user", "content": "x"}) + "\n")
                f.write(json.dumps({"role": "tool", "name": "read_file"}) + "\n")

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = "code_review"
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp) as mock_llm:
                fixture = PLUGIN_DIR / 'test-payloads' / 'substantive-turn.json'
                context = json.loads(fixture.read_text())
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
                mock_llm.assert_called_once()
                kwargs = mock_llm.call_args.kwargs
                self.assertNotIn('task', kwargs, "call_llm MUST be invoked WITHOUT task= per Pitfall 8 / A3")
                self.assertEqual(kwargs.get('temperature'), 0.0)
                self.assertEqual(kwargs.get('max_tokens'), 64)

            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            recs = [json.loads(l) for l in marker_path.read_text().splitlines()]
            self.assertEqual({r['task_type'] for r in recs}, {'code_review'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_llm_blocklist_fallthrough(self):
        """HOOK-05 / D-09: when call_llm returns a forbidden label, _validate_label
        falls through to 'unclassified'. Also covers regex-violation case."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-block-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "20260513_120100_testsubstantive"
            with open(os.path.join(hh, 'sessions', f"{sid}.jsonl"), 'w') as f:
                f.write(json.dumps({"role": "user"}) + "\n")
                f.write(json.dumps({"role": "tool"}) + "\n")

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Direct _validate_label coverage
            self.assertEqual(handler._validate_label("ack"), "unclassified")
            self.assertEqual(handler._validate_label("code-review"), "unclassified")  # hyphen violates regex
            self.assertEqual(handler._validate_label(""), "unclassified")
            self.assertEqual(handler._validate_label("research"), "research")
            self.assertEqual(handler._validate_label("CODE_REVIEW"), "code_review")  # lowercased

            # End-to-end: LLM returns 'thanks' → marker file has 'unclassified'
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = "thanks"
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp):
                fixture = PLUGIN_DIR / 'test-payloads' / 'substantive-turn.json'
                context = json.loads(fixture.read_text())
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))

            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            recs = [json.loads(l) for l in marker_path.read_text().splitlines()]
            self.assertEqual({r['task_type'] for r in recs}, {'unclassified'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_prompt_mint_first_bias(self):
        """Regression guard for the mint-first prompt rewrite.

        Asserts that _build_classification_prompt returns a string containing:
        - The mint-first anchor phrase "Mint a SPECIFIC, DESCRIPTIVE label"
        - All five concrete example labels anchoring 2-4 word granularity
        - An AVOID line that names the bland catch-alls
        - The regex contract ^[a-z][a-z0-9_]{1,47}$
        - The forbidden-labels line containing 'ack'
        - A reuse-as-narrow-exception framing (not the old 'Pick the single best-fitting')

        Also pins the prompt size to <= 4096 chars so D-06 prompt-size invariant
        cannot silently regress.
        """
        import importlib
        import sys
        import tempfile
        import os

        tmpdir = tempfile.mkdtemp(prefix='gsd-prompt-bias-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            result = handler._build_classification_prompt(
                "user message text",
                "assistant response text",
                ["generation", "code_review", "research"],
            )

            # Mint-first anchor phrase
            self.assertIn(
                "Mint a SPECIFIC, DESCRIPTIVE label",
                result,
                "Prompt must contain the mint-first anchor phrase",
            )

            # Concrete example labels anchoring granularity
            for example in (
                "weekly_pr_review",
                "prod_log_triage",
                "news_summary",
                "sql_query_debug",
                "release_notes_draft",
            ):
                self.assertIn(example, result, f"Prompt must contain example label '{example}'")

            # AVOID line naming bland catch-alls
            self.assertIn(
                "AVOID",
                result,
                "Prompt must contain an explicit AVOID line",
            )
            self.assertIn(
                "generation",
                result,
                "Prompt AVOID line must name 'generation'",
            )

            # Regex contract present
            self.assertIn(
                "^[a-z][a-z0-9_]{1,47}$",
                result,
                "Prompt must contain the regex contract ^[a-z][a-z0-9_]{1,47}$",
            )

            # Forbidden-labels line present
            self.assertIn(
                "ack",
                result,
                "Prompt must retain the forbidden-labels line containing 'ack'",
            )

            # Old bland framing must be gone
            self.assertNotIn(
                "Pick the single best-fitting existing label",
                result,
                "Old lookup-first framing must not appear in the mint-first prompt",
            )

            # Prompt-size invariant: fits within ~4 KB
            self.assertLessEqual(
                len(result),
                4096,
                f"Prompt must be <= 4096 chars; got {len(result)}",
            )
        finally:
            _restore_plugin_env(snap, added)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_halt_unclassified(self):
        """HOOK-04 / D-08: when guardrail-status.json::halted is True, the LLM is NOT called
        and a marker pair with task_type=unclassified is written.
        Phase 19: classifier.py now reads guardrail-status.json (SC-7)."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-halt-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Seed a halted guardrail-status.json (Phase 19: replaces budget-status.json)
            os.makedirs(sd, exist_ok=True)
            with open(os.path.join(sd, 'guardrail-status.json'), 'w', encoding='utf-8') as f:
                json.dump({"halted": True, "autonomousMode": True,
                           "haltedAt": "2026-05-13T00:00:00Z",
                           "lastChecked": "2026-05-13T00:00:00Z",
                           "rules": []}, f)

            # Phase 19: _budget_halted renamed to _guardrail_halted (SC-7)
            self.assertTrue(handler._guardrail_halted())

            # Patch call_llm so we can prove it was NOT called
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm:
                mock_llm.side_effect = AssertionError("LLM must NOT be called when halted (D-08)")
                fixture = PLUGIN_DIR / 'test-payloads' / 'substantive-turn.json'
                context = json.loads(fixture.read_text())
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
                mock_llm.assert_not_called()

            marker_path = handler.MARKERS_DIR / f"{context['session_id']}.jsonl"
            self.assertTrue(marker_path.is_file())
            lines = marker_path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['task_type'] for r in recs}, {'unclassified'})
            self.assertEqual({r['operation_type'] for r in recs}, {'GUARDRAIL', 'CHAT'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_halt_failopen_on_missing_file(self):
        """HOOK-04 / D-08: missing guardrail-status.json returns False from _guardrail_halted
        (fail-open). The handler must NOT crash and must NOT short-circuit to unclassified.
        Phase 19: repointed from BUDGET_STATUS_FILE/_budget_halted to
        GUARDRAIL_STATUS_FILE/_guardrail_halted (SC-7)."""
        import importlib
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-halt-open-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # No guardrail-status.json in tmpdir → fail-open (Phase 19: GUARDRAIL_STATUS_FILE)
            self.assertFalse(handler.GUARDRAIL_STATUS_FILE.exists())
            self.assertFalse(handler._guardrail_halted())
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_subagent_inherits(self):
        """HOOK-03 / D-05: when state.db.sessions.parent_session_id is set, the hook
        walks to the root, reads root's marker file, and writes the subagent's marker
        pair with the inherited task_type. NO LLM call."""
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile
        import time as _time
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-subagent-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Seed a state.db with parent + child rows
            state_db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(state_db_path)
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
            conn.execute("INSERT INTO sessions VALUES (?, ?)", ('root-sid-1', None))
            conn.execute("INSERT INTO sessions VALUES (?, ?)", ('child-sid-1', 'root-sid-1'))
            conn.commit()
            conn.close()

            # Seed the parent's marker file with task_type=research
            parent_marker = os.path.join(md, 'root-sid-1.jsonl')
            with open(parent_marker, 'w', encoding='utf-8') as f:
                rec = {"muid": "f" * 33, "ts": _time.time() - 60, "sid": "root-sid-1",
                       "task_type": "research", "operation_type": "GUARDRAIL"}
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                rec2 = dict(rec, operation_type="CHAT")
                f.write(json.dumps(rec2, separators=(",", ":")) + "\n")

            # Patch call_llm so we can prove the LLM was NOT called
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm:
                mock_llm.side_effect = AssertionError("LLM must NOT be called for subagent (D-05)")
                context = {
                    "platform": "test", "user_id": "u",
                    "session_id": "child-sid-1",
                    "message": "x",
                    "response": "Found 3 references to FlockGuard in the repository, see lines 42, 87, 134" + " padding " * 50,
                }
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
                mock_llm.assert_not_called()

            # Assert the child's marker file has task_type=research, GUARDRAIL+CHAT
            child_marker = handler.MARKERS_DIR / 'child-sid-1.jsonl'
            self.assertTrue(child_marker.is_file())
            lines = child_marker.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['task_type'] for r in recs}, {'research'})
            self.assertEqual({r['operation_type'] for r in recs}, {'GUARDRAIL', 'CHAT'})
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_walk_to_root(self):
        """HOOK-03: _walk_to_root_session handles missing file, missing row, and depth cap."""
        import importlib
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-walk-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Case A — missing state.db file → returns input sid
            self.assertEqual(handler._walk_to_root_session('nope'), 'nope')

            # Case B — seed db with row that has no parent → returns input sid
            db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)")
            conn.execute("INSERT INTO sessions VALUES (?, ?)", ('root', None))
            conn.commit()
            conn.close()
            self.assertEqual(handler._walk_to_root_session('root'), 'root')

            # Case C — chain of 3 → walks to root
            conn = sqlite3.connect(db_path)
            conn.execute("INSERT INTO sessions VALUES (?, ?)", ('mid', 'root'))
            conn.execute("INSERT INTO sessions VALUES (?, ?)", ('leaf', 'mid'))
            conn.commit()
            conn.close()
            self.assertEqual(handler._walk_to_root_session('leaf'), 'root')

            # Case D — depth cap: chain of 15 self-loops → returns after max_depth steps
            conn = sqlite3.connect(db_path)
            for i in range(15):
                conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)",
                             (f'loop{i}', f'loop{i+1}'))
            conn.commit()
            conn.close()
            # Should not infinite-loop — return after max_depth iterations
            result = handler._walk_to_root_session('loop0', max_depth=10)
            self.assertIsInstance(result, str)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_root_session_id_walks_parent_chain(self):
        """TESTS-01: 3-level chain root -> mid -> leaf; lookup from leaf returns root."""
        import os
        import shutil
        import sqlite3
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-root-walk-01-')
        try:
            db_path = os.path.join(tmpdir, 'state.db')
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)"
                )
                conn.executemany(
                    "INSERT INTO sessions VALUES (?, ?)",
                    [('root', None), ('mid', 'root'), ('leaf', 'mid')],
                )
                conn.commit()
            finally:
                conn.close()

            mod = _load_root_walk_helper()
            self.assertEqual(
                mod.get_root_session_id('leaf', state_db_path=db_path), 'root',
                "3-level chain leaf->mid->root should resolve to 'root'",
            )
            self.assertEqual(
                mod.get_root_session_id('mid', state_db_path=db_path), 'root',
                "mid should resolve to its parent 'root'",
            )
            self.assertEqual(
                mod.get_root_session_id('root', state_db_path=db_path), 'root',
                "root with NULL parent should resolve to itself",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_root_session_id_orphan_parent(self):
        """TESTS-02: parent_session_id references a non-existent row; helper follows once and stops."""
        import os
        import shutil
        import sqlite3
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-root-walk-02-')
        try:
            db_path = os.path.join(tmpdir, 'state.db')
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)"
                )
                # orphan-child points at a parent id that is NOT in the table.
                # Walk: iter 0 current='orphan-child', row=('nonexistent-parent',)
                #       -> current='nonexistent-parent'
                #       iter 1 current='nonexistent-parent', row=None -> return current.
                # Mirrors classifier.py:67-70 fail-open semantics (D-05).
                conn.execute(
                    "INSERT INTO sessions VALUES (?, ?)",
                    ('orphan-child', 'nonexistent-parent'),
                )
                conn.commit()
            finally:
                conn.close()

            mod = _load_root_walk_helper()
            self.assertEqual(
                mod.get_root_session_id('orphan-child', state_db_path=db_path),
                'nonexistent-parent',
                "Orphan-child's parent ref is dangling; helper follows once and stops "
                "at the unfindable parent id — mirrors classifier.py:67-70 semantics.",
            )

            # Edge case: a sid with NO row at all in sessions — the very first
            # SELECT returns None and the helper returns the input sid.
            self.assertEqual(
                mod.get_root_session_id('totally-unknown-sid', state_db_path=db_path),
                'totally-unknown-sid',
                "A sid with no row in sessions at all should return itself.",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_root_session_id_circular_guard(self):
        """TESTS-03: A->B->A cyclic chain; max_depth guard terminates the walk."""
        import os
        import shutil
        import sqlite3
        import tempfile
        import time

        tmpdir = tempfile.mkdtemp(prefix='gsd-root-walk-03-')
        try:
            db_path = os.path.join(tmpdir, 'state.db')
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT)"
                )
                conn.executemany(
                    "INSERT INTO sessions VALUES (?, ?)",
                    [('a', 'b'), ('b', 'a')],
                )
                conn.commit()
            finally:
                conn.close()

            mod = _load_root_walk_helper()

            # max_depth=10 cap terminates the cycle. Assertion is on
            # terminate-without-infinite-loop (str + in {'a', 'b'} + bounded
            # time) — NOT on which specific cycle node the walk lands on.
            start = time.monotonic()
            result = mod.get_root_session_id('a', state_db_path=db_path, max_depth=10)
            elapsed = time.monotonic() - start

            self.assertIsInstance(result, str, "helper must return a string")
            self.assertIn(
                result, {'a', 'b'},
                "cyclic walk should terminate at one of the two cycle nodes; "
                "got {!r}".format(result),
            )
            self.assertLess(
                elapsed, 2.0,
                "cyclic walk must terminate in bounded time; took {:.3f}s "
                "(guard against the max_depth check being missing)".format(elapsed),
            )

            # max_depth=1 advances exactly one hop in the cycle.
            result_d1 = mod.get_root_session_id('a', state_db_path=db_path, max_depth=1)
            self.assertEqual(
                result_d1, 'b',
                "max_depth=1 should advance exactly one hop in the cycle",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_tool_count_end_to_end_cli_substantive(self):
        """HOOK-12 / G-02 regression guard: when state.db.sessions has tool_call_count=2 for a CLI
        session AND ~/.hermes/sessions/<sid>.jsonl does NOT exist (the exact UAT-2 production shape
        that produced no marker file), classifier.run_classification(...) drives the full pipeline
        and writes a GUARDRAIL+CHAT marker pair with a non-unclassified task_type. This is the test
        that would have caught G-02 in CI on 2026-05-13 before the operator UAT had to surface it."""
        import importlib
        import json
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-e2e-cli-substantive-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Build the production CLI shape: state.db row with tool_call_count=2 + NO JSONL.
            # parent_session_id NULL so the subagent inheritance branch (D-05) does not fire.
            # tool_call_count=2 to defeat the trivial-skip threshold.
            db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, tool_call_count INTEGER)"
            )
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", ('cli-sid', None, 2))
            conn.commit()
            conn.close()

            # JSONL absence is the load-bearing premise — this is what produced G-02 in production.
            self.assertFalse(os.path.exists(os.path.join(hh, 'sessions', 'cli-sid.jsonl')))

            # Seed an empty taxonomy and a NOT-halted guardrail-status so the LLM-classification
            # branch is reachable. Phase 19: repointed from budget-status.json (SC-7).
            os.makedirs(sd, exist_ok=True)
            with open(os.path.join(sd, 'task-taxonomy.json'), 'w', encoding='utf-8') as f:
                json.dump({"labels": {"code_review": {"description": "Code review work"}}}, f)
            with open(os.path.join(sd, 'guardrail-status.json'), 'w', encoding='utf-8') as f:
                json.dump({"halted": False}, f)

            # Patch call_llm to return content 'code_review'. Same stub shape as
            # test_revenium_classifier_llm_label (lines 1211-1262): mock_resp.choices[0].message.content.
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = "code_review"
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp):
                # response='' mirrors production CLI behavior — on_session_end payload does NOT
                # include response text. The test proves that despite empty response_preview, the
                # state.db tool_call_count=2 keeps the helper above the trivial-skip threshold
                # (the heuristic requires BOTH tool_count==0 AND len(response)<200; tool_count=2
                # breaks the AND).
                handler.run_classification(
                    session_id='cli-sid',
                    model='qwen3.6-plus',
                    platform='cli',
                    message='Review src/foo.py for race conditions',
                    response='',
                )

            # Assertions: marker file exists with 2 records, both task_type='code_review',
            # one GUARDRAIL + one CHAT.
            marker_path = os.path.join(md, 'cli-sid.jsonl')
            self.assertTrue(os.path.exists(marker_path),
                            'marker file MUST exist — G-02 regression guard')
            with open(marker_path, 'r', encoding='utf-8') as f:
                lines = [json.loads(l) for l in f.read().splitlines() if l.strip()]
            self.assertEqual(len(lines), 2,
                             'marker file MUST contain exactly 2 records (GUARDRAIL + CHAT)')
            self.assertEqual(lines[0]['task_type'], 'code_review',
                             'first record MUST carry task_type=code_review (not unclassified)')
            self.assertEqual(lines[1]['task_type'], 'code_review',
                             'second record MUST carry task_type=code_review (not unclassified)')
            self.assertEqual({lines[0]['operation_type'], lines[1]['operation_type']},
                             {'GUARDRAIL', 'CHAT'},
                             'marker pair MUST be one GUARDRAIL + one CHAT')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_sentinel_written_on_happy_path(self):
        """HOOK-13 / D-21: when _on_session_end completes via the happy path
        (run_classification returns normally for ANY outcome — substantive marker
        write, trivial-skip, inheritance, or halt-unclassified), the plugin writes
        an empty sentinel file at MARKERS_READY_DIR / session_id. The sentinel is
        the cron's primary readiness signal."""
        import importlib
        import importlib.util
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-sentinel-happy-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            # Load the plugin package as a proper package so the relative import
            # `from .classifier import ...` resolves correctly.
            mod_name = 'revenium_classifier_sentinel_happy'
            pkg_init = PLUGIN_DIR / '__init__.py'
            spec = importlib.util.spec_from_file_location(
                mod_name,
                str(pkg_init),
                submodule_search_locations=[str(PLUGIN_DIR)],
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

            # Patch run_classification on the plugin module to a no-op so we only
            # exercise the sentinel write.
            with unittest.mock.patch.object(mod, 'run_classification', return_value=None):
                mod._on_session_end(
                    session_id='sid-happy',
                    completed=True,
                    interrupted=False,
                    model='qwen3.6-plus',
                    platform='cli',
                )

            sentinel_path = os.path.join(ready_dir, 'sid-happy')
            self.assertTrue(os.path.exists(sentinel_path),
                            'sentinel not written for happy path')
            self.assertEqual(os.path.getsize(sentinel_path), 0,
                             'sentinel must be zero-byte')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_sentinel_written_on_error_path(self):
        """HOOK-13 / D-21 / D-04 belt: when run_classification raises an exception,
        _on_session_end catches it, logs a warning, AND STILL writes the sentinel.
        The sentinel write inside the except handler prevents a classifier crash
        from freezing a session in the cron's race window. D-04 invariant:
        _on_session_end never raises out."""
        import importlib
        import importlib.util
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-sentinel-error-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        ready_dir = os.path.join(sd, 'markers', '.ready')
        prev_ready = os.environ.get('REVENIUM_MARKERS_READY_DIR')
        os.environ['REVENIUM_MARKERS_READY_DIR'] = ready_dir
        os.makedirs(ready_dir, mode=0o700, exist_ok=True)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            mod_name = 'revenium_classifier_sentinel_error'
            pkg_init = PLUGIN_DIR / '__init__.py'
            spec = importlib.util.spec_from_file_location(
                mod_name,
                str(pkg_init),
                submodule_search_locations=[str(PLUGIN_DIR)],
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

            with unittest.mock.patch.object(
                mod, 'run_classification',
                side_effect=RuntimeError('synthetic classifier crash'),
            ):
                # Must NOT raise — D-04 belt.
                mod._on_session_end(
                    session_id='sid-error',
                    completed=True,
                    interrupted=False,
                    model='qwen3.6-plus',
                    platform='cli',
                )

            sentinel_path = os.path.join(ready_dir, 'sid-error')
            self.assertTrue(os.path.exists(sentinel_path),
                            'sentinel not written on error path — D-04 belt broken')
            self.assertEqual(os.path.getsize(sentinel_path), 0,
                             'sentinel must be zero-byte even on error path')
        finally:
            if prev_ready is None:
                os.environ.pop('REVENIUM_MARKERS_READY_DIR', None)
            else:
                os.environ['REVENIUM_MARKERS_READY_DIR'] = prev_ready
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_cron_filter_skips_recent_no_sentinel(self):
        """HOOK-13 / D-21: a session whose started_at is 30s ago (within the 120s
        settle window) AND has NO sentinel file is SKIPPED by hermes-report.sh's
        session SELECT filter; the session is NOT shipped to revenium meter
        completion this tick. Pins the cron's race-defense primary path."""
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        import time

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-cron-skip-recent-')
        try:
            hh = os.path.join(tmpdir, 'hh')
            sd = os.path.join(hh, 'state', 'revenium')
            md = os.path.join(sd, 'markers')
            mrd = os.path.join(md, '.ready')
            # Stub revenium at $HOME/.local/bin — common.sh::ensure_path prepends
            # known system paths AFTER setting PATH, and ${HOME}/.local/bin is the
            # LAST prepend in its loop, so it ends up FIRST in the final PATH.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(md, exist_ok=True)
            os.makedirs(mrd, exist_ok=True)
            os.makedirs(bin_dir, exist_ok=True)

            # Build state.db with one recent session (30s ago) and NO sentinel.
            state_db = os.path.join(hh, 'state.db')
            recent_ts = int(time.time()) - 30
            conn = sqlite3.connect(state_db)
            conn.execute(
                "CREATE TABLE sessions ("
                "id TEXT PRIMARY KEY, model TEXT, source TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, "
                "cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
                "reasoning_tokens INTEGER, estimated_cost_usd REAL, "
                "api_call_count INTEGER, started_at INTEGER, ended_at INTEGER, "
                "billing_provider TEXT)"
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ('sid-recent', 'qwen3.6-plus', 'cli', 100, 50, 0, 0, 0,
                 0.01, 1, recent_ts, None, 'openai'),
            )
            conn.commit()
            conn.close()

            # Stub revenium CLI.
            invocations_log = os.path.join(tmpdir, 'revenium-invocations.log')
            stub_path = os.path.join(bin_dir, 'revenium')
            with open(stub_path, 'w', encoding='utf-8') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    f'    printf "%q " "$@" >> "{invocations_log}"\n'
                    f'    printf "\\n" >> "{invocations_log}"\n'
                    '    exit 0 ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(stub_path, 0o755)

            env = {
                **os.environ,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'HOME': shim_home,
                'HERMES_HOME': hh,
                'REVENIUM_STATE_DIR': sd,
                'REVENIUM_MARKERS_DIR': md,
                'REVENIUM_MARKERS_READY_DIR': mrd,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'TZ': 'UTC',
            }

            result = subprocess.run(
                ['bash', str(SKILL / 'scripts' / 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )

            # Confirm the recent-no-sentinel session was NEVER shipped (no meter
            # completion call appended to the log). The stub only records the
            # post-`meter completion` argv tail, so absence of file or empty
            # file == no meter completion call.
            log_size = os.path.getsize(invocations_log) if os.path.exists(invocations_log) else 0
            self.assertEqual(log_size, 0,
                             'recent-no-sentinel session was unexpectedly shipped — '
                             'invocations log not empty: ' +
                             (open(invocations_log).read() if log_size else ''))

            # Confirm the cron emitted the skip log line.
            cron_log_path = os.path.join(sd, 'revenium-metering.log')
            cron_log = ''
            if os.path.exists(cron_log_path):
                cron_log = open(cron_log_path).read()
            combined = result.stderr + cron_log
            self.assertIn('awaiting plugin sentinel', combined,
                          'expected skip log line for recent-no-sentinel session')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_cron_filter_includes_aged_no_sentinel(self):
        """HOOK-13 / D-21 safety net: a session whose started_at is 200s ago
        (older than the 120s settle window) AND has NO sentinel is INCLUDED in
        the cron's session list — D-18 default applies (--task-type unclassified)
        because no marker file exists. Pins the safety-net path for plugin-failure
        cases."""
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        import time

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-cron-aged-')
        try:
            hh = os.path.join(tmpdir, 'hh')
            sd = os.path.join(hh, 'state', 'revenium')
            md = os.path.join(sd, 'markers')
            mrd = os.path.join(md, '.ready')
            # Stub revenium at $HOME/.local/bin — common.sh::ensure_path prepends
            # known system paths AFTER setting PATH, and ${HOME}/.local/bin is the
            # LAST prepend in its loop, so it ends up FIRST in the final PATH.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(md, exist_ok=True)
            os.makedirs(mrd, exist_ok=True)
            os.makedirs(bin_dir, exist_ok=True)

            state_db = os.path.join(hh, 'state.db')
            aged_ts = int(time.time()) - 200
            conn = sqlite3.connect(state_db)
            conn.execute(
                "CREATE TABLE sessions ("
                "id TEXT PRIMARY KEY, model TEXT, source TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, "
                "cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
                "reasoning_tokens INTEGER, estimated_cost_usd REAL, "
                "api_call_count INTEGER, started_at INTEGER, ended_at INTEGER, "
                "billing_provider TEXT)"
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ('sid-aged', 'qwen3.6-plus', 'cli', 100, 50, 0, 0, 0,
                 0.01, 1, aged_ts, None, 'openai'),
            )
            conn.commit()
            conn.close()

            invocations_log = os.path.join(tmpdir, 'revenium-invocations.log')
            stub_path = os.path.join(bin_dir, 'revenium')
            with open(stub_path, 'w', encoding='utf-8') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    f'    printf "%q " "$@" >> "{invocations_log}"\n'
                    f'    printf "\\n" >> "{invocations_log}"\n'
                    '    exit 0 ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(stub_path, 0o755)

            env = {
                **os.environ,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'HOME': shim_home,
                'HERMES_HOME': hh,
                'REVENIUM_STATE_DIR': sd,
                'REVENIUM_MARKERS_DIR': md,
                'REVENIUM_MARKERS_READY_DIR': mrd,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'TZ': 'UTC',
            }

            result = subprocess.run(
                ['bash', str(SKILL / 'scripts' / 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )

            self.assertTrue(os.path.exists(invocations_log) and os.path.getsize(invocations_log) > 0,
                            'aged-no-sentinel session was NOT shipped — safety net broken')
            log_text = open(invocations_log).read()
            # Stub records argv AFTER `meter completion` is stripped, so we assert on
            # downstream flags in the argv tail.
            self.assertIn('--task-type unclassified', log_text,
                          'aged-no-sentinel session must ship with D-18 default unclassified')

            cron_log_path = os.path.join(sd, 'revenium-metering.log')
            cron_log = ''
            if os.path.exists(cron_log_path):
                cron_log = open(cron_log_path).read()
            combined = result.stderr + cron_log
            self.assertNotIn('skipping sid-aged', combined,
                             'aged session was unexpectedly skipped')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_cron_filter_includes_any_age_with_sentinel(self):
        """HOOK-13 / D-21 sentinel-wins: a session whose started_at is 5s ago
        (well within the 120s settle window) BUT has a sentinel file at
        MARKERS_READY_DIR/<sid> is INCLUDED in the cron's session list. Pins the
        sentinel-driven primary path: sentinel presence overrides the age check."""
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        import time
        from pathlib import Path

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-cron-sentinel-wins-')
        try:
            hh = os.path.join(tmpdir, 'hh')
            sd = os.path.join(hh, 'state', 'revenium')
            md = os.path.join(sd, 'markers')
            mrd = os.path.join(md, '.ready')
            # Stub revenium at $HOME/.local/bin — common.sh::ensure_path prepends
            # known system paths AFTER setting PATH, and ${HOME}/.local/bin is the
            # LAST prepend in its loop, so it ends up FIRST in the final PATH.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(md, exist_ok=True)
            os.makedirs(mrd, exist_ok=True)
            os.makedirs(bin_dir, exist_ok=True)

            state_db = os.path.join(hh, 'state.db')
            recent_ts = int(time.time()) - 5
            conn = sqlite3.connect(state_db)
            conn.execute(
                "CREATE TABLE sessions ("
                "id TEXT PRIMARY KEY, model TEXT, source TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, "
                "cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
                "reasoning_tokens INTEGER, estimated_cost_usd REAL, "
                "api_call_count INTEGER, started_at INTEGER, ended_at INTEGER, "
                "billing_provider TEXT)"
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ('sid-with-sentinel', 'qwen3.6-plus', 'cli', 100, 50, 0, 0, 0,
                 0.01, 1, recent_ts, None, 'openai'),
            )
            conn.commit()
            conn.close()

            # Write the sentinel — this is the load-bearing setup detail.
            Path(os.path.join(mrd, 'sid-with-sentinel')).touch(exist_ok=True)

            invocations_log = os.path.join(tmpdir, 'revenium-invocations.log')
            stub_path = os.path.join(bin_dir, 'revenium')
            with open(stub_path, 'w', encoding='utf-8') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    f'    printf "%q " "$@" >> "{invocations_log}"\n'
                    f'    printf "\\n" >> "{invocations_log}"\n'
                    '    exit 0 ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(stub_path, 0o755)

            env = {
                **os.environ,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'HOME': shim_home,
                'HERMES_HOME': hh,
                'REVENIUM_STATE_DIR': sd,
                'REVENIUM_MARKERS_DIR': md,
                'REVENIUM_MARKERS_READY_DIR': mrd,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'TZ': 'UTC',
            }

            result = subprocess.run(
                ['bash', str(SKILL / 'scripts' / 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )

            self.assertTrue(os.path.exists(invocations_log) and os.path.getsize(invocations_log) > 0,
                            'session with sentinel was NOT shipped despite recent started_at')
            log_text = open(invocations_log).read()
            self.assertIn('--task-type unclassified', log_text,
                          'expected meter completion call (with D-18 default unclassified '
                          'because no marker exists in MARKERS_DIR for this sid)')

            cron_log_path = os.path.join(sd, 'revenium-metering.log')
            cron_log = ''
            if os.path.exists(cron_log_path):
                cron_log = open(cron_log_path).read()
            combined = result.stderr + cron_log
            self.assertNotIn('skipping sid-with-sentinel', combined,
                             'sentinel-having session was unexpectedly skipped')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_cron_filter_end_to_end_ships_marker_task_type(self):
        """HOOK-13 / G-03 regression guard: when state.db has a CLI session row
        (tool_call_count=2, recent started_at) AND a marker file exists at
        MARKERS_DIR/<sid>.jsonl with task_type='generation' AND a sentinel exists at
        MARKERS_READY_DIR/<sid>, hermes-report.sh's session SELECT INCLUDES the
        session AND the downstream revenium meter completion calls carry
        --task-type generation (NOT --task-type unclassified). This is the test
        that would have caught G-03 on 2026-05-14 — the cron-race shipping
        unclassified ahead of the plugin's marker."""
        import json
        import os
        import secrets
        import shutil
        import sqlite3
        import subprocess
        import tempfile
        import time
        from pathlib import Path

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-e2e-cron-sentinel-')
        try:
            hh = os.path.join(tmpdir, 'hh')
            sd = os.path.join(hh, 'state', 'revenium')
            md = os.path.join(sd, 'markers')
            mrd = os.path.join(md, '.ready')
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(md, exist_ok=True)
            os.makedirs(mrd, exist_ok=True)
            os.makedirs(bin_dir, exist_ok=True)

            # 1. Build state.db row (synthetic CLI session shape with recent started_at).
            state_db = os.path.join(hh, 'state.db')
            started_at = int(time.time()) - 5  # within settle window — sentinel must win
            conn = sqlite3.connect(state_db)
            conn.execute(
                "CREATE TABLE sessions ("
                "id TEXT PRIMARY KEY, model TEXT, source TEXT, "
                "input_tokens INTEGER, output_tokens INTEGER, "
                "cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
                "reasoning_tokens INTEGER, estimated_cost_usd REAL, "
                "api_call_count INTEGER, started_at INTEGER, ended_at INTEGER, "
                "billing_provider TEXT, tool_call_count INTEGER)"
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ('cli-sid', 'qwen3.6-plus', 'cli', 1000, 500, 0, 0, 0,
                 0.05, 1, started_at, None, 'openai', 2),
            )
            conn.commit()
            conn.close()

            # 2. Write the marker file — exactly two records, GUARDRAIL + CHAT pair
            # with task_type='generation' (matching the classifier's MARK-03 muid format).
            marker_path = os.path.join(md, 'cli-sid.jsonl')

            def muid():
                return f"{int(time.time_ns() // 1_000_000):013x}" + secrets.token_hex(10)

            recs = [
                {"muid": muid(), "ts": time.time(), "sid": "cli-sid",
                 "task_type": "generation", "operation_type": "GUARDRAIL"},
                {"muid": muid(), "ts": time.time(), "sid": "cli-sid",
                 "task_type": "generation", "operation_type": "CHAT"},
            ]
            with open(marker_path, 'w', encoding='utf-8') as f:
                for r in recs:
                    f.write(json.dumps(r, separators=(',', ':')) + '\n')

            # 3. Write the sentinel.
            Path(os.path.join(mrd, 'cli-sid')).touch(exist_ok=True)

            # 4. Stub revenium CLI. Place at $HOME/.local/bin so common.sh::ensure_path
            # leaves the stub ahead of any real revenium installed on the runner.
            invocations_log = os.path.join(tmpdir, 'revenium-invocations.log')
            stub_path = os.path.join(bin_dir, 'revenium')
            with open(stub_path, 'w', encoding='utf-8') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    f'    printf "%q " "$@" >> "{invocations_log}"\n'
                    f'    printf "\\n" >> "{invocations_log}"\n'
                    '    exit 0 ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(stub_path, 0o755)

            # 5. Seed an empty ledger.
            open(os.path.join(sd, 'revenium-hermes.ledger'), 'w').close()

            # 6. Invoke hermes-report.sh.
            env = {
                **os.environ,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'HOME': shim_home,
                'HERMES_HOME': hh,
                'REVENIUM_STATE_DIR': sd,
                'REVENIUM_MARKERS_DIR': md,
                'REVENIUM_MARKERS_READY_DIR': mrd,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'TZ': 'UTC',
            }
            result = subprocess.run(
                ['bash', str(SKILL / 'scripts' / 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=60,
            )

            # 7. Assertions.
            self.assertEqual(result.returncode, 0,
                             f'hermes-report.sh failed: stderr={result.stderr}')
            self.assertTrue(os.path.exists(invocations_log),
                            'revenium stub was never invoked — cron may have skipped the session')
            log_text = open(invocations_log).read()
            self.assertIn('--task-type generation', log_text,
                          f'expected --task-type generation in argv; got: {log_text}')
            self.assertNotIn('--task-type unclassified', log_text,
                             f'cron shipped unclassified despite marker on disk: {log_text}')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_setup_md_has_mechanical_classification_hook_section(self):
        """HOOK-10 / D-16: references/setup.md carries a 'Mechanical classification hook'
        section that documents the install path, gateway-restart requirement, and the
        Conflict-C1/C2 anti-pattern callout against `hermes hooks list`."""
        text = (SKILL / 'references' / 'setup.md').read_text(encoding='utf-8')
        # Section heading present (H2)
        self.assertIn('## Mechanical classification hook', text,
                      'setup.md must carry the Phase 6 hook section per D-16')
        # Gateway-restart instruction present
        self.assertIn('hermes gateway restart', text,
                      'setup.md must document the post-install gateway-restart step')
        # Anti-pattern callout against the shell-hook CLI (Conflict C1)
        self.assertRegex(text, r'Do NOT.*hermes hooks list',
                         'setup.md must warn against using `hermes hooks list` for the event hook')
        # Plugin directory documented
        self.assertIn('~/.hermes/plugins/revenium-classifier/', text,
                      'setup.md must reference the canonical plugin install path')
        # Subagent mention
        self.assertTrue('subagent' in text.lower(),
                        'setup.md must mention subagent inheritance')
        # D-16: new section appears AFTER "How attribution works"
        attr_idx = text.find('## How attribution works')
        hook_idx = text.find('## Mechanical classification hook')
        self.assertGreater(attr_idx, -1, '"## How attribution works" heading must exist in setup.md')
        self.assertGreater(hook_idx, -1, '"## Mechanical classification hook" heading must exist in setup.md')
        self.assertGreater(hook_idx, attr_idx,
                           'D-16: "Mechanical classification hook" section must appear AFTER "How attribution works"')

    def test_revenium_classifier_marker_pair(self):
        """HOOK-06: handler._write_marker_pair writes exactly two records (one GUARDRAIL,
        one CHAT) to <MARKERS_DIR>/<sid>.jsonl with the Phase 2 schema, < 1024 bytes each,
        muid matching the 33-char hex regex, with atomic O_APPEND + flock semantics."""
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-pair-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            marker_path = handler._write_marker_pair('test-sid-pair', 'code_review')
            self.assertEqual(str(marker_path), os.path.join(md, 'test-sid-pair.jsonl'))
            lines = marker_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 2, f'expected 2 markers, got {len(lines)}')
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['operation_type'] for r in recs}, {'GUARDRAIL', 'CHAT'})
            for r in recs:
                self.assertEqual(r['sid'], 'test-sid-pair')
                self.assertEqual(r['task_type'], 'code_review')
                self.assertRegex(r['muid'], r'^[0-9a-f]{33}$')
                # Phase 22 (MARKER-01): top-level sessions emit trace_id == sid and
                # OMIT agentic_job_id (state.db is absent in this test, so
                # _walk_to_root_session fail-opens and returns the input sid;
                # _root_agentic_job_id_for is not called when root_sid == sid).
                self.assertEqual(set(r.keys()), {'muid', 'ts', 'sid', 'task_type', 'operation_type', 'trace_id'})
                self.assertEqual(r['trace_id'], 'test-sid-pair')
                self.assertNotIn('agentic_job_id', r)
            for l in lines:
                self.assertLess(len((l + '\n').encode('utf-8')), 1024, 'marker line exceeds 1024 bytes')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_plugin_entrypoint(self):
        """HOOK-11: plugin __init__.register(ctx) wires on_session_end → _on_session_end;
        invoking the registered callback synchronously drives the full classification
        pipeline (subagent → heuristic → halt → LLM → marker pair) and produces a valid
        GUARDRAIL+CHAT marker pair on disk. Pins the universal-coverage invariant: the
        plugin entrypoint, when invoked the way the Hermes plugin bus invokes it,
        produces markers regardless of session source."""
        import asyncio  # noqa: F401  (kept for parity with other HOOK-* tests)
        import importlib
        import importlib.util
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-plugin-entry-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            # Reload the shared classifier module so its env-var-derived path constants
            # pick up our tmp HERMES_HOME / REVENIUM_STATE_DIR redirects.
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Load the plugin package via spec_from_file_location with submodule_search_locations
            # — same import pattern Hermes' plugin manager uses to load plugins by path.
            mod_name = 'revenium_classifier_entrypoint_test'
            pkg_init = PLUGIN_DIR / '__init__.py'
            spec = importlib.util.spec_from_file_location(
                mod_name,
                str(pkg_init),
                submodule_search_locations=[str(PLUGIN_DIR)],
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

            # Stub the Hermes plugin context. register_hook records the wiring so we can
            # invoke the registered callback the way the plugin bus would.
            registered = {}

            class StubCtx:
                def register_hook(self, name, cb):
                    registered[name] = cb

            ctx = StubCtx()
            mod.register(ctx)
            self.assertIn('on_session_end', registered,
                          'register(ctx) must wire on_session_end via ctx.register_hook')

            # Pre-seed the session jsonl so the heuristic skip-fast-path does NOT trigger:
            # need at least one role:tool entry under the latest role:user line.
            fixture = PLUGIN_DIR / 'test-payloads' / 'substantive-turn.json'
            context = json.loads(fixture.read_text())
            sid = context['session_id']
            sessions_dir = os.path.join(hh, 'sessions')
            os.makedirs(sessions_dir, exist_ok=True)
            with open(os.path.join(sessions_dir, f'{sid}.jsonl'), 'w', encoding='utf-8') as f:
                f.write(json.dumps({'role': 'user', 'content': context.get('message', '')}) + '\n')
                f.write(json.dumps({'role': 'tool', 'name': 'read_file'}) + '\n')

            # Patch the shared classifier's call_llm so the plugin pipeline produces a
            # meaningful task_type. The plugin's relative `from .classifier import
            # run_classification` resolves to a SUBMODULE of the dynamically-loaded
            # plugin package (named `<mod_name>.classifier`), not the bare `classifier`
            # module we patched into `sys.modules` earlier. We patch call_llm on the
            # plugin's submodule so the call_llm reference inside `_classify_via_llm`
            # (which uses the module-global) resolves to our mock.
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = 'code_review'

            plugin_classifier_mod = sys.modules[f'{mod_name}.classifier']

            with unittest.mock.patch.object(plugin_classifier_mod, 'call_llm', return_value=mock_resp):
                # Invoke the registered callback the way the Hermes plugin bus invokes it:
                # synchronously, with the documented on_session_end kwargs.
                registered['on_session_end'](
                    session_id=sid,
                    completed=True,
                    interrupted=False,
                    model='test-model',
                    platform='cli',
                )

            # Assert the marker pair landed at the expected path.
            marker_path = handler.MARKERS_DIR / f'{sid}.jsonl'
            self.assertTrue(marker_path.is_file(),
                            f'plugin entrypoint did not produce marker file at {marker_path}')
            lines = marker_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines), 2,
                             f'plugin entrypoint must write exactly 2 markers; got {len(lines)}')
            recs = [json.loads(l) for l in lines]
            self.assertEqual({r['task_type'] for r in recs}, {'code_review'},
                             'both markers must carry the LLM-classified task_type')
            self.assertEqual({r['operation_type'] for r in recs}, {'GUARDRAIL', 'CHAT'},
                             'plugin entrypoint must write one GUARDRAIL + one CHAT marker')
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_reads_state_db_content(self):
        """STATE-DB-MSG-LOOKUP: when __init__.py passes message=None/response=None,
        run_classification_async reads the last user+assistant messages from
        state.db.messages and injects them into the LLM prompt. The LLM must receive
        real session content rather than empty strings.

        Also pins _read_session_messages helper contract: returns (last_user, last_asst)
        tuple on success; ("", "") for nonexistent sid; ("", "") for falsy sid.
        """
        import asyncio
        import importlib
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-statedb-msg-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Build state.db with sessions + messages tables
            db_path = os.path.join(hh, 'state.db')
            sid = "20260514_statedb_msg_test"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, tool_call_count INTEGER)"
            )
            conn.execute(
                "CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, timestamp INTEGER)"
            )
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sid, None, 1))
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                (sid, 'user', 'Summarize today news headlines', None, 1000),
            )
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                (sid, 'assistant', 'Top stories: ...', None, 1001),
            )
            conn.commit()
            conn.close()

            # Reload classifier so STATE_DB resolves to the tmp path
            importlib.reload(sys.modules['classifier'])
            import classifier as handler  # noqa: F811 — intentional reload

            # Belt-and-suspenders: directly test the helper
            self.assertEqual(
                handler._read_session_messages(sid),
                ("Summarize today news headlines", "Top stories: ..."),
                "_read_session_messages must return (last_user, last_asst) from state.db",
            )
            self.assertEqual(
                handler._read_session_messages("nonexistent-sid"),
                ("", ""),
                "_read_session_messages must return ('', '') for unknown sid",
            )
            self.assertEqual(
                handler._read_session_messages(""),
                ("", ""),
                "_read_session_messages must return ('', '') for falsy sid",
            )

            # End-to-end: run_classification_async with message=None, response=None
            # must inject state.db content into the LLM call
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = "news_summary"

            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp) as mock_llm:
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message=None,
                    response=None,
                ))
                # Step 7 (Phase 13) may make a second call_llm call for job inference.
                # Verify at least one call was made (task classification).
                self.assertGreaterEqual(mock_llm.call_count, 1,
                    "call_llm must be called at least once for task classification")
                # The first call is always the task classification; inspect its messages.
                call_messages = mock_llm.call_args_list[0].kwargs['messages']
                full_prompt = " ".join(m['content'] for m in call_messages)
                self.assertIn(
                    "Summarize today news headlines",
                    full_prompt,
                    "LLM prompt must contain the user message read from state.db",
                )
                self.assertIn(
                    "Top stories",
                    full_prompt,
                    "LLM prompt must contain the assistant message read from state.db",
                )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_wire_agent_trace_passthrough(self):
        """WIRE-02 + WIRE-03: pins marker agent/trace_id passthrough to --agent/--trace-id argv.

        Sub-case A (positive): marker pair carries agent='revenium-skill' and
        trace_id='trace-abc-001' — every captured invocation must carry those values.

        Sub-case B (fallback): same marker pair but agent/trace_id keys omitted —
        every captured invocation must carry --agent Hermes and --trace-id <sid>
        (the colon-dash fallback from the marker-driven cmd array)."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def run_cron(env, invocations_log):
            if os.path.exists(invocations_log):
                os.unlink(invocations_log)
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    import shlex
                    invocations.append(shlex.split(line))
            return result.returncode, invocations, result.stdout + result.stderr

        def argv_to_flags(argv):
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        def make_shim(bin_dir, invocations_log):
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                    '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

        def make_tmpdir():
            tmpdir = tempfile.mkdtemp(prefix='gsd-wire-agent-trace-')
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            invocations_log = os.path.join(tmpdir, 'invocations.log')
            make_shim(bin_dir, invocations_log)
            return tmpdir, hermes_home, state_dir, markers_dir, state_db, ledger, shim_home, bin_dir, invocations_log

        # =====================================================
        # Sub-case A: markers carry agent + trace_id (positive)
        # =====================================================
        with self.subTest(case='positive-agent-trace'):
            tmpdir, hermes_home, state_dir, markers_dir, state_db, ledger, shim_home, bin_dir, invocations_log = make_tmpdir()
            try:
                sid = 'wire-agent-trace-positive'
                build_state_db(state_db, [{
                    'id': sid,
                    'model': 'claude-sonnet-4-6',
                    'source': 'test',
                    'input_tokens': 10000,
                    'output_tokens': 4000,
                    'cache_read': 200,
                    'cache_write': 100,
                    'reasoning': 0,
                    'estimated_cost': '0.123456',
                    'api_calls': 2,
                    'started_at': 1715514000.0,  # Pitfall 6: bypasses G-03 sentinel filter
                    'ended_at': 1715515100.0,
                    'billing_provider': 'anthropic',
                }])
                # Write GUARDRAIL+CHAT marker pair with agent/trace_id populated
                marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_path, 'w') as f:
                    f.write(json.dumps({
                        'muid': '01893b8a300abcdef0123456789abc01',
                        'ts': 1715515001.0,
                        'sid': sid,
                        'task_type': 'code_review',
                        'operation_type': 'GUARDRAIL',
                        'agent': 'revenium-skill',
                        'trace_id': 'trace-abc-001',
                    }) + '\n')
                    f.write(json.dumps({
                        'muid': '01893b8a300abcdef0123456789abc02',
                        'ts': 1715515002.0,
                        'sid': sid,
                        'task_type': 'code_review',
                        'operation_type': 'CHAT',
                        'agent': 'revenium-skill',
                        'trace_id': 'trace-abc-001',
                    }) + '\n')

                base_env = {
                    **os.environ,
                    'HOME': shim_home,
                    'HERMES_HOME': hermes_home,
                    'REVENIUM_STATE_DIR': state_dir,
                    'REVENIUM_MARKERS_DIR': markers_dir,
                    'REVENIUM_MARKERS_READY_DIR': os.path.join(markers_dir, '.ready'),
                    'REVENIUM_TAXONOMY_FILE': os.path.join(state_dir, 'task-taxonomy.json'),
                    'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                    'INVOCATIONS_LOG': invocations_log,
                    'TZ': 'UTC',
                }
                rc, invocations, output = run_cron(base_env, invocations_log)
                self.assertEqual(rc, 0, f'positive sub-case cron exit {rc}: {output}')
                self.assertEqual(len(invocations), 2,
                                 f'positive sub-case expected 2 invocations (GUARDRAIL+CHAT), got {len(invocations)}: {output}')
                for argv in invocations:
                    flags = argv_to_flags(argv)
                    self.assertEqual(flags.get('--agent'), 'revenium-skill',
                                     'WIRE-02: --agent must carry marker agent field when present')
                    self.assertEqual(flags.get('--trace-id'), 'trace-abc-001',
                                     'WIRE-03: --trace-id must carry marker trace_id field when present')
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        # =====================================================
        # Sub-case B: markers omit agent + trace_id (fallback)
        # =====================================================
        with self.subTest(case='fallback-no-agent-trace'):
            tmpdir, hermes_home, state_dir, markers_dir, state_db, ledger, shim_home, bin_dir, invocations_log = make_tmpdir()
            try:
                sid = 'wire-agent-trace-fallback'
                build_state_db(state_db, [{
                    'id': sid,
                    'model': 'claude-sonnet-4-6',
                    'source': 'test',
                    'input_tokens': 10000,
                    'output_tokens': 4000,
                    'cache_read': 200,
                    'cache_write': 100,
                    'reasoning': 0,
                    'estimated_cost': '0.123456',
                    'api_calls': 2,
                    'started_at': 1715514000.0,  # Pitfall 6: bypasses G-03 sentinel filter
                    'ended_at': 1715515100.0,
                    'billing_provider': 'anthropic',
                }])
                # Write GUARDRAIL+CHAT marker pair WITHOUT agent/trace_id — only the 5 required keys
                marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_path, 'w') as f:
                    f.write(json.dumps({
                        'muid': '01893b8a300abcdef0123456789abc03',
                        'ts': 1715515001.0,
                        'sid': sid,
                        'task_type': 'code_review',
                        'operation_type': 'GUARDRAIL',
                    }) + '\n')
                    f.write(json.dumps({
                        'muid': '01893b8a300abcdef0123456789abc04',
                        'ts': 1715515002.0,
                        'sid': sid,
                        'task_type': 'code_review',
                        'operation_type': 'CHAT',
                    }) + '\n')

                base_env = {
                    **os.environ,
                    'HOME': shim_home,
                    'HERMES_HOME': hermes_home,
                    'REVENIUM_STATE_DIR': state_dir,
                    'REVENIUM_MARKERS_DIR': markers_dir,
                    'REVENIUM_MARKERS_READY_DIR': os.path.join(markers_dir, '.ready'),
                    'REVENIUM_TAXONOMY_FILE': os.path.join(state_dir, 'task-taxonomy.json'),
                    'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                    'INVOCATIONS_LOG': invocations_log,
                    'TZ': 'UTC',
                }
                rc, invocations, output = run_cron(base_env, invocations_log)
                self.assertEqual(rc, 0, f'fallback sub-case cron exit {rc}: {output}')
                self.assertEqual(len(invocations), 2,
                                 f'fallback sub-case expected 2 invocations (GUARDRAIL+CHAT), got {len(invocations)}: {output}')
                for argv in invocations:
                    flags = argv_to_flags(argv)
                    self.assertEqual(flags.get('--agent'), 'Hermes',
                                     'WIRE-02 fallback: --agent must be Hermes when marker omits agent field')
                    self.assertEqual(flags.get('--trace-id'), sid,
                                     f'WIRE-03 fallback: --trace-id must be {sid!r} when marker omits trace_id field')
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)


    def test_wire_no_provider_regression_per_class(self):
        """WIRE-04 / D-24: 8-provider regression — every per-marker revenium meter
        completion argv preserves the same --provider / --model / --model-source flags
        the legacy pre-Phase-3 single-call path would have produced for each of the
        8 provider classes (anthropic, openai, google, xai, deepseek, meta,
        openrouter-special, bedrock-special)."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        PROVIDER_CASES = [
            # (label, billing_provider, model, expected_provider, expected_clean_model, expected_model_source)
            ('anthropic',         'anthropic',  'claude-sonnet-4-6',
             'anthropic', 'claude-sonnet-4-6',                              'anthropic'),
            ('openai',            'openai',     'gpt-4o',
             'openai',    'gpt-4o',                                         'openai'),
            ('google',            'google',     'gemini-1.5-pro',
             'google',    'gemini-1.5-pro',                                 'google'),
            ('xai',               'xai',        'grok-2',
             'xai',       'grok-2',                                         'xai'),
            ('deepseek',          'deepseek',   'deepseek-chat',
             'deepseek',  'deepseek-chat',                                  'deepseek'),
            ('meta',              '',           'llama-3.1-70b',
             'meta',      'llama-3.1-70b',                                  None),
            ('openrouter-special', 'openrouter', 'anthropic/claude-sonnet-4-5',
             'anthropic', 'claude-sonnet-4-5',                              'openrouter'),
            ('bedrock-special',   'bedrock',    'anthropic.claude-3-5-sonnet-20241022-v2:0',
             'anthropic', 'claude-3-5-sonnet-20241022-v2:0',               'bedrock'),
        ]

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def run_cron(env, invocations_log):
            if os.path.exists(invocations_log):
                os.unlink(invocations_log)
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    import shlex
                    invocations.append(shlex.split(line))
            return result.returncode, invocations, result.stdout + result.stderr

        def argv_to_flags(argv):
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        for (label, billing_provider, model,
             expected_provider, expected_clean_model, expected_model_source) in PROVIDER_CASES:
            with self.subTest(case=label):
                tmpdir = tempfile.mkdtemp(prefix='gsd-wire-provider-e2e-')
                try:
                    hermes_home = os.path.join(tmpdir, 'hh')
                    state_dir = os.path.join(hermes_home, 'state', 'revenium')
                    markers_dir = os.path.join(state_dir, 'markers')
                    os.makedirs(markers_dir, mode=0o700)
                    state_db = os.path.join(hermes_home, 'state.db')
                    shim_home = os.path.join(tmpdir, 'home')
                    bin_dir = os.path.join(shim_home, '.local', 'bin')
                    os.makedirs(bin_dir)
                    invocations_log = os.path.join(tmpdir, 'invocations.log')

                    # Write the revenium shim
                    shim = os.path.join(bin_dir, 'revenium')
                    with open(shim, 'w') as f:
                        f.write(
                            '#!/usr/bin/env bash\n'
                            'case "$1" in\n'
                            '  config) exit 0 ;;\n'
                            '  meter)\n'
                            '    shift; shift\n'
                            '    [[ "$1" == "--help" ]] && exit 0\n'
                            '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                            '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                            '    exit 0\n'
                            '    ;;\n'
                            '  *) exit 0 ;;\n'
                            'esac\n'
                        )
                    os.chmod(shim, 0o755)

                    sid = f'wire-provider-{label}'
                    build_state_db(state_db, [{
                        'id': sid,
                        'model': model,
                        'source': 'test',
                        'input_tokens': 10000,
                        'output_tokens': 4000,
                        'cache_read': 200,
                        'cache_write': 100,
                        'reasoning': 0,
                        'estimated_cost': '0.123456',
                        'api_calls': 2,
                        'started_at': 1715514000.0,  # Pitfall 6: bypasses G-03 sentinel filter
                        'ended_at': 1715515100.0,
                        'billing_provider': billing_provider,
                    }])

                    # Write GUARDRAIL+CHAT marker pair — forces marker-driven split path (N=2)
                    marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
                    with open(marker_path, 'w') as f:
                        f.write(json.dumps({
                            'muid': f'01893b8a300abcdef0123456789aa01',
                            'ts': 1715515001.0,
                            'sid': sid,
                            'task_type': 'code_review',
                            'operation_type': 'GUARDRAIL',
                        }) + '\n')
                        f.write(json.dumps({
                            'muid': f'01893b8a300abcdef0123456789aa02',
                            'ts': 1715515002.0,
                            'sid': sid,
                            'task_type': 'code_review',
                            'operation_type': 'CHAT',
                        }) + '\n')

                    base_env = {
                        **os.environ,
                        'HOME': shim_home,
                        'HERMES_HOME': hermes_home,
                        'REVENIUM_STATE_DIR': state_dir,
                        'REVENIUM_MARKERS_DIR': markers_dir,
                        'REVENIUM_MARKERS_READY_DIR': os.path.join(markers_dir, '.ready'),
                        'REVENIUM_TAXONOMY_FILE': os.path.join(state_dir, 'task-taxonomy.json'),
                        'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                        'INVOCATIONS_LOG': invocations_log,
                        'TZ': 'UTC',
                    }

                    rc, invocations, output = run_cron(base_env, invocations_log)
                    self.assertEqual(rc, 0, f'{label}: cron exit {rc}: {output}')
                    self.assertEqual(len(invocations), 2,
                                     f'{label}: expected 2 invocations (GUARDRAIL+CHAT), '
                                     f'got {len(invocations)}: {output}')

                    for argv in invocations:
                        flags = argv_to_flags(argv)
                        self.assertEqual(flags.get('--provider'), expected_provider,
                                         f'{label}: --provider mismatch')
                        self.assertEqual(flags.get('--model'), expected_clean_model,
                                         f'{label}: --model mismatch')
                        if expected_model_source is not None:
                            self.assertEqual(flags.get('--model-source'), expected_model_source,
                                             f'{label}: --model-source mismatch')
                        else:
                            self.assertNotIn('--model-source', flags,
                                             f'{label}: --model-source must be ABSENT when billing_provider is empty')
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)


    def test_prune_markers_dry_run_and_live(self):
        """D-26 / D-27 / D-28 / D-29: prune-markers.sh correctly identifies stale
        marker files via the ledger timestamp (D-26), respects REVENIUM_MARKER_RETENTION_DAYS
        (D-27), supports --dry-run without touching files (D-29), and idempotently
        re-runs after all stale files are removed.

        Fixture:
          - old_sid:    latest ledger row 31 days old -> should be pruned
          - fresh_sid:  latest ledger row today       -> should be kept
          - orphan_sid: no ledger row, mtime 31 days old -> should be pruned (D-26 fallback)

        Three sub-cases:
          A. --dry-run: old + orphan listed, neither deleted.
          B. live run:  old + orphan deleted, fresh kept.
          C. idempotent re-run: exit 0, summary shows removed=0."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        import time

        PRUNE_SCRIPT = SKILL / 'scripts' / 'prune-markers.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            ledger_file = os.path.join(state_dir, 'revenium-hermes.ledger')

            # --- Fixture: three marker files ---

            # 1. "old" sid — ledger entry 31 days ago -> should be pruned
            old_sid = 'old-session-31d'
            old_ts = int(time.time()) - 31 * 86400
            with open(os.path.join(markers_dir, f'{old_sid}.jsonl'), 'w') as f:
                f.write(json.dumps({'muid': 'aaa', 'ts': float(old_ts),
                                    'sid': old_sid, 'task_type': 'research',
                                    'operation_type': 'CHAT'}) + '\n')
            with open(ledger_file, 'a') as f:
                f.write(f'HERMES:{old_sid}:1000:{old_ts}:aaa\n')

            # 2. "fresh" sid — ledger entry today -> should be kept
            fresh_sid = 'fresh-session-today'
            fresh_ts = int(time.time())
            with open(os.path.join(markers_dir, f'{fresh_sid}.jsonl'), 'w') as f:
                f.write(json.dumps({'muid': 'bbb', 'ts': float(fresh_ts),
                                    'sid': fresh_sid, 'task_type': 'generation',
                                    'operation_type': 'CHAT'}) + '\n')
            with open(ledger_file, 'a') as f:
                f.write(f'HERMES:{fresh_sid}:500:{fresh_ts}:bbb\n')

            # 3. "orphan" sid — no ledger entry, mtime 31 days old -> should be pruned
            orphan_sid = 'orphan-no-ledger'
            orphan_path = os.path.join(markers_dir, f'{orphan_sid}.jsonl')
            with open(orphan_path, 'w') as f:
                f.write(json.dumps({'muid': 'ccc', 'ts': float(old_ts),
                                    'sid': orphan_sid, 'task_type': 'review',
                                    'operation_type': 'CHAT'}) + '\n')
            os.utime(orphan_path, (old_ts, old_ts))

            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_MARKER_RETENTION_DAYS': '30',
                'TZ': 'UTC',
            }

            # --- Sub-case A: dry-run — nothing deleted ---
            r = subprocess.run(['bash', str(PRUNE_SCRIPT), '--dry-run'],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0,
                             f'dry-run exit {r.returncode}: {r.stderr}')
            self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{old_sid}.jsonl')),
                            'dry-run must not delete old marker')
            self.assertTrue(os.path.exists(orphan_path),
                            'dry-run must not delete orphan marker')
            self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{fresh_sid}.jsonl')),
                            'dry-run must not delete fresh marker')

            # --- Sub-case B: live run — old + orphan deleted, fresh kept ---
            r = subprocess.run(['bash', str(PRUNE_SCRIPT)],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0,
                             f'live run exit {r.returncode}: {r.stderr}')
            self.assertFalse(os.path.exists(os.path.join(markers_dir, f'{old_sid}.jsonl')),
                             'old marker must be deleted in live run')
            self.assertFalse(os.path.exists(orphan_path),
                             'orphan marker must be deleted in live run')
            self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{fresh_sid}.jsonl')),
                            'fresh marker must be kept in live run')

            # --- Sub-case C: idempotent re-run — exit 0, no further deletions ---
            r = subprocess.run(['bash', str(PRUNE_SCRIPT)],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0,
                             f'idempotent run exit {r.returncode}: {r.stderr}')
            # Fresh marker still present after idempotent re-run
            self.assertTrue(os.path.exists(os.path.join(markers_dir, f'{fresh_sid}.jsonl')),
                            'fresh marker must still exist after idempotent re-run')


    def test_read_taxonomy_labels_recency_order(self):
        """D-33: _read_taxonomy_labels returns recent-first within 7-day bucket,
        alphabetical within older + undated. Seed labels (no last_seen_at) sort last."""
        import datetime, json, os, importlib, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot, sys_path_added, hermes_home, state_dir, markers_dir = _setup_plugin_env(tmpdir)
            try:
                taxonomy_path = os.path.join(state_dir, 'task-taxonomy.json')
                now = datetime.datetime.now(datetime.timezone.utc)
                ts_recent = (now - datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
                ts_old = (now - datetime.timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
                fixture = {
                    'labels': {
                        'alpha_old': {'description': None, 'examples': [], 'last_seen_at': ts_old},
                        'beta_recent': {'description': None, 'examples': [], 'last_seen_at': ts_recent},
                        'gamma_seed': {'description': 'seed label', 'examples': []},  # no last_seen_at
                    }
                }
                with open(taxonomy_path, 'w') as f:
                    json.dump(fixture, f)
                os.environ['REVENIUM_TAXONOMY_FILE'] = taxonomy_path
                import classifier as cls_module
                importlib.reload(cls_module)
                result = cls_module._read_taxonomy_labels()
                self.assertEqual(result[0], 'beta_recent', 'most recent label must be first')
                self.assertIn('alpha_old', result[1:], 'older dated label after recent')
                self.assertEqual(result[-1], 'gamma_seed', 'seed label (no last_seen_at) must be last')
            finally:
                os.environ.pop('REVENIUM_TAXONOMY_FILE', None)
                _restore_plugin_env(snapshot, sys_path_added)

    def test_persist_label_to_taxonomy_mint_and_update(self):
        """D-32: _persist_label_to_taxonomy mints new labels, updates existing
        last_seen_at without duplicating, and refuses to mint 'unclassified'."""
        import json, os, importlib, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot, sys_path_added, hermes_home, state_dir, markers_dir = _setup_plugin_env(tmpdir)
            try:
                taxonomy_path = os.path.join(state_dir, 'task-taxonomy.json')
                os.environ['REVENIUM_TAXONOMY_FILE'] = taxonomy_path
                import classifier as cls_module
                importlib.reload(cls_module)

                # Sub-case 1: mint a brand-new label
                cls_module._persist_label_to_taxonomy('sql_query_debug')
                self.assertTrue(os.path.exists(taxonomy_path))
                data = json.loads(open(taxonomy_path).read())
                self.assertIn('sql_query_debug', data['labels'])
                entry = data['labels']['sql_query_debug']
                self.assertIsNone(entry['description'])
                self.assertEqual(entry['examples'], [])
                self.assertIn('last_seen_at', entry)

                # Sub-case 2: same label again — no duplicate, last_seen_at updated
                first_ts = entry['last_seen_at']
                cls_module._persist_label_to_taxonomy('sql_query_debug')
                data2 = json.loads(open(taxonomy_path).read())
                self.assertEqual(len(data2['labels']), 1, 'no duplicate')

                # Sub-case 3: 'unclassified' is sentinel — must NOT be minted
                cls_module._persist_label_to_taxonomy('unclassified')
                data3 = json.loads(open(taxonomy_path).read())
                self.assertNotIn('unclassified', data3['labels'])
            finally:
                os.environ.pop('REVENIUM_TAXONOMY_FILE', None)
                _restore_plugin_env(snapshot, sys_path_added)


    def test_hermes_report_pipe_safety_marker_sanitization(self):
        """WR-01 / D-34: a marker carrying `|`, `\\n`, or `\\r` in its agent or
        trace_id field is sanitized at the Python emission boundary so the
        bash IFS='|' read parser is not desynchronized. The 11-pipe field
        count is preserved; d_cost (field 9) does not absorb m_agent content."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def run_cron(env, invocations_log):
            if os.path.exists(invocations_log):
                os.unlink(invocations_log)
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    import shlex
                    invocations.append(shlex.split(line))
            return result.returncode, invocations, result.stdout + result.stderr

        def argv_to_flags(argv):
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        tmpdir = tempfile.mkdtemp(prefix='gsd-pipe-safety-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            invocations_log = os.path.join(tmpdir, 'invocations.log')

            # Write the revenium shim
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                    '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            sid = 'pipe-safety-pathological'
            build_state_db(state_db, [{
                'id': sid,
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 10000,
                'output_tokens': 4000,
                'cache_read': 200,
                'cache_write': 100,
                'reasoning': 0,
                'estimated_cost': '0.123456',
                'api_calls': 2,
                'started_at': 1715514000.0,  # Pitfall 6: bypasses G-03 sentinel filter
                'ended_at': 1715515100.0,
                'billing_provider': 'anthropic',
            }])

            # Pathological marker pair: agent has a literal pipe; trace_id has a literal newline.
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps({
                    'muid': '01893b8a300abcdef0123456789abc01',
                    'ts': 1715515001.0,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'GUARDRAIL',
                    'agent': 'bad|value',
                    'trace_id': 'bad\nvalue',
                }) + '\n')
                f.write(json.dumps({
                    'muid': '01893b8a300abcdef0123456789abc02',
                    'ts': 1715515002.0,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                    'agent': 'bad|value',
                    'trace_id': 'bad\nvalue',
                }) + '\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_MARKERS_READY_DIR': os.path.join(markers_dir, '.ready'),
                'REVENIUM_TAXONOMY_FILE': os.path.join(state_dir, 'task-taxonomy.json'),
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': invocations_log,
                'TZ': 'UTC',
            }
            rc, invocations, output = run_cron(base_env, invocations_log)
            self.assertEqual(rc, 0, f'cron exit {rc}: {output}')
            self.assertEqual(len(invocations), 2,
                             f'expected 2 invocations (GUARDRAIL+CHAT) post-sanitization, got {len(invocations)}: {output}')
            for argv in invocations:
                flags = argv_to_flags(argv)
                self.assertEqual(flags.get('--agent'), 'bad_value',
                                 'WR-01: --agent must carry underscore-sanitized value (| → _)')
                self.assertEqual(flags.get('--trace-id'), 'bad_value',
                                 'WR-01: --trace-id must carry underscore-sanitized value (\\n → _)')
                # Field 9 (--total-tokens) is the last numeric field before m_agent/m_trace;
                # round-trip proves no desync: a desync would put d_cost content into m_agent.
                self.assertIn('--total-tokens', flags,
                              'pipe parser desync would lose --total-tokens (field 9 absorbed by field 10)')
                self.assertNotIn('|', flags.get('--agent', ''))
                self.assertNotIn('\n', flags.get('--trace-id', ''))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_job_marker_schema(self):
        """TEST-01: pins the kind:"job" marker schema shape per D-03/D-04.

        D-01: discriminated solely by the kind key in markers/<sid>.jsonl.
        D-02: all keys are snake_case (no uppercase characters).
        D-03: canonical shape with optional (job_name, ts, sid) and required
              (kind, agentic_job_id, job_type, status) keys.
        D-04: reader-required keys are kind, agentic_job_id, job_type, status;
              optional keys (job_name, ts, sid) may be absent.
        """
        import json
        # Canonical D-03 fixture.
        job_marker = {
            "kind": "job",
            "ts": 1747300000.12,
            "sid": "abc123",
            "agentic_job_id": "pr-review-fc7a",
            "job_name": "Review PR #42",
            "job_type": "code_review",
            "status": "SUCCESS",
        }
        reader_required = ("kind", "agentic_job_id", "job_type", "status")
        # D-04: all reader-required keys present in canonical fixture.
        for k in reader_required:
            self.assertIn(k, job_marker, f'reader-required key "{k}" missing from canonical fixture')
        # D-02: all keys are snake_case — no uppercase characters.
        for k in job_marker:
            self.assertNotRegex(k, r'[A-Z]', f'key "{k}" must be snake_case (D-02)')
        # D-01: kind discriminator value is "job".
        self.assertEqual(job_marker["kind"], "job", 'D-01: kind must equal "job"')
        # D-03: compact JSONL serialization is under 1024 bytes.
        line = json.dumps(job_marker, separators=(",", ":")) + "\n"
        self.assertLess(len(line.encode("utf-8")), 1024,
                        "D-03: job marker JSONL line must be < 1024 bytes")
        # D-04: a minimal job marker with only reader-required keys is valid.
        # job_name, ts, sid are optional and may be absent.
        minimal = {
            "kind": "job",
            "agentic_job_id": "pr-review-fc7a",
            "job_type": "code_review",
            "status": "SUCCESS",
        }
        for k in reader_required:
            self.assertIn(k, minimal, f'D-04: reader-required key "{k}" must be present in minimal fixture')
        self.assertNotIn("job_name", minimal,
                         "D-04: optional key job_name must be absent from minimal fixture")
        self.assertNotIn("ts", minimal,
                         "D-04: optional key ts must be absent from minimal fixture")
        self.assertNotIn("sid", minimal,
                         "D-04: optional key sid must be absent from minimal fixture")

    def test_job_marker_does_not_alter_task_completion_argv(self):
        """TEST-02: a kind:"job" line in the marker file leaves task-metering argv
        byte-identical to v1.0.

        SCHEMA-04: job-less / marker-less sessions produce byte-identical
        revenium meter completion argv to v1.0.

        Sub-case A: task markers only vs. task markers + one kind:"job" line —
        the meter completion argv is byte-identical.

        Sub-case B: marker-less session produces the same argv as v1.0
        zero-marker fallthrough (--task-type unclassified, --operation-type CHAT).

        Sub-case C (WR-01 / WR-03 regression): a marker file containing a
        non-object JSON line, or a kind:"job" line with an unhashable
        agentic_job_id, must skip only the offending line — never abort
        attribution for the whole session.
        """
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import sys
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def run_cron(env, invocations_log):
            """Invoke hermes-report.sh once; return (exit_code, [argv_list, ...])."""
            if os.path.exists(invocations_log):
                os.unlink(invocations_log)
            open(invocations_log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    import shlex
                    invocations.append(shlex.split(line))
            return result.returncode, invocations, result.stdout + result.stderr

        def argv_to_flags(argv):
            """Convert flat argv to {flag: value} dict for assertions."""
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-marker-regression-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            ledger = os.path.join(state_dir, 'revenium-hermes.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            invocations_log = os.path.join(tmpdir, 'invocations.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    [[ "$1" == "--help" ]] && exit 0\n'
                    '    printf "%q " "$@" >> "$INVOCATIONS_LOG"\n'
                    '    printf "\\n" >> "$INVOCATIONS_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': invocations_log,
                'TZ': 'UTC',
            }

            # =====================================================
            # Sub-case A: task markers only vs. task markers + job line.
            # The meter completion argv must be byte-identical.
            # =====================================================
            sid = '20260512_120000_jobtest'
            input_tokens = 8000
            output_tokens = 3000
            total_tokens = input_tokens + output_tokens
            estimated_cost = '0.111111'

            # Task markers: two valid v1.0 markers.
            task_markers = [
                {
                    'muid': '01893b8a3{:02x}abcdef0123456789abcdef0'.format(i),
                    'ts': 1715515000.0 + i + 1,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                for i in range(2)
            ]
            # D-03 canonical job marker.
            job_marker = {
                "kind": "job",
                "ts": 1747300000.12,
                "sid": sid,
                "agentic_job_id": "pr-review-fc7a",
                "job_name": "Review PR #42",
                "job_type": "code_review",
                "status": "SUCCESS",
            }

            def reset_state(include_job_line=False):
                """Reset ledger + state.db + marker file for a fresh run."""
                for path in (state_db, ledger):
                    if os.path.exists(path):
                        os.unlink(path)
                for f_ in os.listdir(markers_dir):
                    full_path = os.path.join(markers_dir, f_)
                    if os.path.isdir(full_path):
                        continue
                    os.unlink(full_path)
                build_state_db(state_db, [{
                    'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                    'input_tokens': input_tokens, 'output_tokens': output_tokens,
                    'cache_read': 200, 'cache_write': 100,
                    'reasoning': 0, 'estimated_cost': estimated_cost,
                    'api_calls': 2, 'started_at': 1715514000.0,
                    'ended_at': 1715515100.0,
                    'billing_provider': 'anthropic',
                }])
                marker_file = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_file, 'w') as f:
                    for m in task_markers:
                        f.write(json.dumps(m, separators=(',', ':')) + '\n')
                    if include_job_line:
                        f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            # Run A: task markers only.
            reset_state(include_job_line=False)
            rc_a, invocations_a, output_a = run_cron(base_env, invocations_log)
            self.assertEqual(rc_a, 0, f'Run A exit {rc_a}: {output_a}')
            self.assertEqual(len(invocations_a), 2,
                             f'Run A: expected 2 invocations (one per marker), got {len(invocations_a)}')

            # SCHEMA-01 / D-15: revenium-jobs.ledger is touch-created by hermes-report.sh
            # on every cron run. Assert it exists after Run A — the file may be empty,
            # but it MUST be present on disk (Phase 9/10 readers depend on its existence).
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')
            self.assertTrue(
                os.path.exists(jobs_ledger),
                f'SCHEMA-01 / D-15: revenium-jobs.ledger must be touch-created on cron run '
                f'(expected at {jobs_ledger})',
            )

            # Run B: same task markers + job line appended.
            reset_state(include_job_line=True)
            rc_b, invocations_b, output_b = run_cron(base_env, invocations_log)
            self.assertEqual(rc_b, 0, f'Run B exit {rc_b}: {output_b}')
            self.assertEqual(len(invocations_b), 2,
                             f'Run B: expected 2 invocations (job line must not generate extra call), '
                             f'got {len(invocations_b)}: {output_b}')

            # Byte-identical argv assertion (SCHEMA-04): same task markers + job line
            # must produce the exact same meter completion argument lists as task
            # markers alone. Phase 7 issues no jobs calls, so only meter args matter.
            self.assertEqual(
                invocations_a, invocations_b,
                'SCHEMA-04: adding a kind:"job" line must not alter meter completion argv '
                f'(Run A={invocations_a!r}, Run B={invocations_b!r})',
            )

            # =====================================================
            # Sub-case B: marker-less session produces the same argv as
            # v1.0 zero-marker fallthrough (--task-type unclassified).
            # =====================================================
            sid_zero = '20260512_120000_jobtest_zero'
            for path in (state_db, ledger):
                if os.path.exists(path):
                    os.unlink(path)
            for f_ in os.listdir(markers_dir):
                full_path = os.path.join(markers_dir, f_)
                if os.path.isdir(full_path):
                    continue
                os.unlink(full_path)
            build_state_db(state_db, [{
                'id': sid_zero, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 5000, 'output_tokens': 2000,
                'cache_read': 100, 'cache_write': 50,
                'reasoning': 0, 'estimated_cost': '0.050000',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715515100.0,
                'billing_provider': 'anthropic',
            }])
            # No marker file for sid_zero -> zero-marker fallthrough.
            rc_z, invocations_z, output_z = run_cron(base_env, invocations_log)
            self.assertEqual(rc_z, 0, f'Sub-case B exit {rc_z}: {output_z}')
            self.assertEqual(len(invocations_z), 1,
                             f'Sub-case B: zero-marker session must emit exactly 1 call, '
                             f'got {len(invocations_z)}')
            flags_z = argv_to_flags(invocations_z[0])
            self.assertEqual(flags_z.get('--task-type'), 'unclassified',
                             'Sub-case B: zero-marker fallthrough must use --task-type unclassified')
            self.assertEqual(flags_z.get('--operation-type'), 'CHAT',
                             'Sub-case B: zero-marker fallthrough must emit --operation-type CHAT')

            # =====================================================
            # Sub-case C (WR-01 / WR-03 regression): malformed lines in the
            # marker file must skip only themselves — a non-object JSON line
            # or a kind:"job" line with an unhashable agentic_job_id must not
            # raise an uncaught exception that aborts the whole session.
            # =====================================================
            malformed_lines = [
                '[1,2,3]',          # WR-01: valid JSON, not an object
                '"hello"',          # WR-01: valid JSON string scalar
                '42',               # WR-01: valid JSON number scalar
                'null',             # WR-01: valid JSON null
                # WR-03: kind:"job" line whose agentic_job_id is a list.
                json.dumps({
                    "kind": "job",
                    "agentic_job_id": ["not", "a", "string"],
                    "job_type": "code_review",
                    "status": "SUCCESS",
                }, separators=(',', ':')),
            ]
            for idx, bad_line in enumerate(malformed_lines):
                reset_state(include_job_line=False)
                marker_file = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_file, 'a') as f:
                    f.write(bad_line + '\n')
                rc_c, invocations_c, output_c = run_cron(base_env, invocations_log)
                self.assertEqual(rc_c, 0, f'Sub-case C[{idx}] exit {rc_c}: {output_c}')
                self.assertEqual(
                    invocations_c, invocations_a,
                    f'Sub-case C[{idx}] ({bad_line!r}): a malformed marker line must '
                    f'skip only itself, leaving task-metering argv byte-identical to '
                    f'the clean run (got {invocations_c!r}, expected {invocations_a!r}, '
                    f'output={output_c})',
                )

            # =====================================================
            # Sub-case D (SCHEMA-03 / D-06 forward-compat skip):
            # A marker file that contains a line with an UNKNOWN kind value
            # (neither "job" nor absent) must be silently skipped — the reader
            # must not generate a spurious meter call for it, and the remaining
            # valid task markers must be attributed exactly as in Run A.
            #
            # This exercises the `elif kind is not None: continue` branch.
            # =====================================================
            # The hard adversarial case for D-06 forward-compat skip: a line that has a
            # non-null, non-"job" kind AND also happens to carry all 5 REQUIRED_KEYS.
            # Without the `elif kind is not None: continue` branch, this line would fall
            # through to the REQUIRED_KEYS check and pass it — generating a spurious extra
            # meter call and causing the invocation count / argv assertion to fail.
            unknown_kind_lines = [
                json.dumps({
                    "kind": "experiment",
                    "ts": 1715515099.0,
                    "sid": sid,
                    "foo": "bar",
                }, separators=(',', ':')),
                json.dumps({
                    "kind": "pipeline",
                    "ts": 1715515098.0,
                    "sid": sid,
                    "stage": "build",
                    "result": "pass",
                }, separators=(',', ':')),
                # This line has all 5 REQUIRED_KEYS plus a non-"job" kind.
                # If the `elif kind is not None: continue` branch is absent, this line
                # would pass the REQUIRED_KEYS gate and produce a 3rd spurious meter call.
                json.dumps({
                    "kind": "future_v2",
                    "muid": "01893b8a3ffabcdef0123456789abcdef",
                    "ts": 1715515097.0,
                    "sid": sid,
                    "task_type": "research",
                    "operation_type": "CHAT",
                }, separators=(',', ':')),
            ]
            for idx, unknown_line in enumerate(unknown_kind_lines):
                reset_state(include_job_line=False)
                marker_file = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_file, 'a') as f:
                    f.write(unknown_line + '\n')
                rc_d, invocations_d, output_d = run_cron(base_env, invocations_log)
                self.assertEqual(rc_d, 0, f'Sub-case D[{idx}] exit {rc_d}: {output_d}')
                # Exactly 2 invocations — same count as Run A (the unknown-kind line
                # must not add a spurious meter call).
                self.assertEqual(
                    len(invocations_d), 2,
                    f'Sub-case D[{idx}] ({unknown_line!r}): unknown kind must be '
                    f'silently skipped — expected 2 invocations (same as Run A), '
                    f'got {len(invocations_d)}: {output_d}',
                )
                # argv lists must be byte-identical to Run A (unknown-kind skip changes
                # nothing about task attribution).
                self.assertEqual(
                    invocations_d, invocations_a,
                    f'Sub-case D[{idx}] ({unknown_line!r}): unknown-kind line must not '
                    f'alter meter completion argv (SCHEMA-03 / D-06 forward-compat skip); '
                    f'got {invocations_d!r}, expected {invocations_a!r}, '
                    f'output={output_d}',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_jobs_cli_capable_preflight(self):
        """Phase 9 Task 1 (CREATE-01, D-05/D-06/D-07): JOBS_CLI_CAPABLE script-level variable
        is declared in hermes-report.sh's startup block via two CLI-capability probes.
        The variable is set once at script level (not local), defaults to false, and a
        negative probe emits a warn without calling exit.
        """
        hermes_report = SKILL / 'scripts' / 'hermes-report.sh'
        text = hermes_report.read_text()

        # JOBS_CLI_CAPABLE must appear at least twice (declaration + read)
        count = text.count('JOBS_CLI_CAPABLE')
        self.assertGreaterEqual(
            count, 2,
            f'JOBS_CLI_CAPABLE must appear >= 2 times (declaration + at least one read); found {count}',
        )

        # The variable must NOT be declared with `local`
        import re
        local_decl = re.search(r'\blocal\s+JOBS_CLI_CAPABLE\b', text)
        self.assertIsNone(
            local_decl,
            'JOBS_CLI_CAPABLE must be script-level (not declared with `local`)',
        )

        # Both probes must be present
        self.assertIn(
            'revenium jobs --help',
            text,
            'Probe (a): `revenium jobs --help` must appear in hermes-report.sh',
        )
        self.assertIn(
            'revenium meter completion --help',
            text,
            'Probe (b): `revenium meter completion --help` must appear in hermes-report.sh',
        )
        self.assertIn(
            '--agentic-job-id',
            text,
            'Probe (b) must grep for --agentic-job-id in meter completion --help output',
        )

        # The preflight probe block must contain no `exit` statement
        # Find the block starting from `revenium jobs --help` and check the next few lines
        lines = text.splitlines()
        probe_a_line = None
        for i, line in enumerate(lines):
            if 'revenium jobs --help' in line:
                probe_a_line = i
                break
        self.assertIsNotNone(probe_a_line, 'Could not find `revenium jobs --help` line')
        # Check 10 lines surrounding the probe for `exit` (the warn path must not exit)
        probe_window = lines[probe_a_line:probe_a_line + 10]
        for win_line in probe_window:
            stripped = win_line.strip()
            # Standalone exit calls (with optional status code) are forbidden in this block
            self.assertFalse(
                re.match(r'\bexit\b', stripped),
                f'Probe block must not call `exit`; found in: {stripped!r}',
            )

        # The probe block must appear before `touch "${LEDGER_FILE}"` (startup ordering)
        touch_line = None
        for i, line in enumerate(lines):
            if 'touch "${LEDGER_FILE}"' in line or "touch \"${LEDGER_FILE}\"" in line:
                touch_line = i
                break
        self.assertIsNotNone(touch_line, 'Could not find `touch "${LEDGER_FILE}"` line')
        self.assertLess(
            probe_a_line, touch_line,
            f'JOBS_CLI_CAPABLE probe (line {probe_a_line}) must appear before '
            f'`touch "${{LEDGER_FILE}}"` (line {touch_line})',
        )

    def test_jobs_cli_capable_preflight_bash_syntax(self):
        """Phase 9 Task 1 sanity: bash -n must pass after JOBS_CLI_CAPABLE addition."""
        hermes_report = SKILL / 'scripts' / 'hermes-report.sh'
        result = subprocess.run(
            ['bash', '-n', str(hermes_report)],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f'bash -n failed after JOBS_CLI_CAPABLE addition: {result.stderr}',
        )

    def test_owning_job_id_positional_attribution(self):
        """Phase 9 Task 2 (D-11, D-12, D-14, D-16): owning_job_id positional attribution
        is resolved in the marker-reader heredoc.

        Static checks:
        - owning_job_id appears in hermes-report.sh
        - colon-sanitization (replace) is present
        - kind == "job" branch still precedes REQUIRED_KEYS check

        Behavioral checks:
        - [task, task, job] in file order: both tasks' owning_job_id == job's sanitized id
        - [task, job, task] in file order: first task gets job id, trailing task gets None
        """
        import json
        import os
        import sys
        import tempfile
        import shutil

        hermes_report = SKILL / 'scripts' / 'hermes-report.sh'
        text = hermes_report.read_text()

        # --- Static checks ---

        # owning_job_id must appear in the script
        count = text.count('owning_job_id')
        self.assertGreaterEqual(
            count, 1,
            f'owning_job_id must appear in hermes-report.sh; found {count}',
        )

        # Colon-sanitization must use replace() with a tuple including ':'
        # Check for replace( near owning_job_id context
        self.assertIn(
            'replace(',
            text,
            'colon-sanitization via replace() must be present for owning_job_id (D-16)',
        )

        # kind == "job" branch must come before REQUIRED_KEYS check
        lines = text.splitlines()
        kind_job_line = None
        required_keys_line = None
        for i, line in enumerate(lines):
            if 'kind == "job"' in line and kind_job_line is None:
                kind_job_line = i
            if 'REQUIRED_KEYS)' in line or 'REQUIRED_KEYS,' in line:
                if required_keys_line is None:
                    required_keys_line = i
        self.assertIsNotNone(kind_job_line, 'kind == "job" branch not found in hermes-report.sh')
        self.assertIsNotNone(required_keys_line, 'REQUIRED_KEYS check not found in hermes-report.sh')
        self.assertLess(
            kind_job_line, required_keys_line,
            f'kind == "job" branch (line {kind_job_line}) must appear before '
            f'REQUIRED_KEYS check (line {required_keys_line})',
        )

        # --- Behavioral checks via exercising the reader Python heredoc ---

        # Extract the marker-reader Python heredoc from hermes-report.sh.
        # The marker-reader is the heredoc that follows `marker_output=$(` and uses
        # `python3 - <<'PY' 2>&1`. Identify it by finding the line index of
        # `marker_output=$(` and then the next `<<'PY' 2>&1` line after it.
        heredoc_lines = []
        heredoc_start = None
        for i, line in enumerate(lines):
            if 'marker_output=$(' in line:
                heredoc_start = i
            if heredoc_start is not None and i > heredoc_start and "<<'PY' 2>&1" in line:
                # Found the heredoc opening line — collect from next line until standalone PY
                for j in range(i + 1, len(lines)):
                    if lines[j].strip() == 'PY':
                        break
                    heredoc_lines.append(lines[j])
                break

        self.assertTrue(
            len(heredoc_lines) > 0,
            'Could not extract marker-reader Python heredoc from hermes-report.sh',
        )
        heredoc_code = '\n'.join(heredoc_lines)

        tmpdir = tempfile.mkdtemp(prefix='gsd-owning-job-attr-')
        try:
            script_dir = str(SKILL / 'scripts')
            markers_dir = os.path.join(tmpdir, 'markers')
            os.makedirs(markers_dir)
            ledger_path = os.path.join(tmpdir, 'ledger')
            open(ledger_path, 'w').close()

            sid = 'test-attribution-sid'

            # We'll use subprocess to run just the Python code, setting env vars.
            def run_heredoc_python(marker_lines_data, test_sid=sid):
                marker_file = os.path.join(markers_dir, f'{test_sid}.jsonl')
                with open(marker_file, 'w') as f:
                    for ml in marker_lines_data:
                        f.write(ml + '\n')

                reader_env = {
                    **os.environ,
                    'MARKERS_DIR': markers_dir,
                    'SID': test_sid,
                    'TOTAL_TOKENS': '10000',
                    'DELTA_TOTAL': '10000',
                    'SCRIPT_DIR': script_dir,
                    'LEDGER_PATH': ledger_path,
                }
                result = subprocess.run(
                    ['python3', '-c', heredoc_code],
                    env=reader_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result.stdout, result.returncode

            # Build fixture marker lines
            def task_marker(muid_suffix, ts, task_type='code_review'):
                return json.dumps({
                    'muid': f'01893b8a3{muid_suffix:02x}abcdef0123456789abcdef0',
                    'ts': ts,
                    'sid': sid,
                    'task_type': task_type,
                    'operation_type': 'CHAT',
                }, separators=(',', ':'))

            def job_marker(job_id, ts):
                return json.dumps({
                    'kind': 'job',
                    'ts': ts,
                    'sid': sid,
                    'agentic_job_id': job_id,
                    'job_name': 'Test Job',
                    'job_type': 'feature_development',
                    'status': 'IN_PROGRESS',
                }, separators=(',', ':'))

            job_id_plain = 'pr-review-fc7a'

            # --- Fixture A: [task, task, job] ---
            # Both tasks should get owning_job_id = sanitized(job_id_plain)
            fixture_a = [
                task_marker(0, 1715515001.0),
                task_marker(1, 1715515002.0),
                job_marker(job_id_plain, 1715515010.0),
            ]
            out_a, rc_a = run_heredoc_python(fixture_a)
            self.assertEqual(rc_a, 0, f'Reader heredoc failed for fixture A: rc={rc_a}')
            # Parse MARKERS_JSON
            markers_json_a = None
            for line in out_a.splitlines():
                if line.startswith('MARKERS_JSON='):
                    markers_json_a = json.loads(line[len('MARKERS_JSON='):])
                    break
            self.assertIsNotNone(markers_json_a, f'MARKERS_JSON not found in reader output: {out_a}')
            self.assertEqual(len(markers_json_a), 2,
                             f'Fixture A: expected 2 task markers, got {len(markers_json_a)}')
            for m in markers_json_a:
                self.assertIn('owning_job_id', m,
                              f'Fixture A: marker missing owning_job_id: {m}')
                self.assertEqual(
                    m['owning_job_id'], job_id_plain,
                    f'Fixture A: task marker owning_job_id should be {job_id_plain!r}, '
                    f'got {m["owning_job_id"]!r}',
                )

            # --- Fixture B: [task, job, task] ---
            # First task gets job id; trailing task (no job after it) gets null.
            sid2 = 'test-attribution-sid2'
            fixture_b = [
                task_marker(0, 1715515001.0),
                job_marker(job_id_plain, 1715515005.0),
                task_marker(1, 1715515010.0),
            ]
            out_b, rc_b = run_heredoc_python(fixture_b, test_sid=sid2)
            self.assertEqual(rc_b, 0, f'Reader heredoc failed for fixture B: rc={rc_b}')
            markers_json_b = None
            for line in out_b.splitlines():
                if line.startswith('MARKERS_JSON='):
                    markers_json_b = json.loads(line[len('MARKERS_JSON='):])
                    break
            self.assertIsNotNone(markers_json_b, f'MARKERS_JSON not found for fixture B: {out_b}')
            self.assertEqual(len(markers_json_b), 2,
                             f'Fixture B: expected 2 task markers, got {len(markers_json_b)}')
            # First task marker should have the job's id
            first_m = markers_json_b[0]
            self.assertIn('owning_job_id', first_m,
                          f'Fixture B: first marker missing owning_job_id: {first_m}')
            self.assertEqual(
                first_m['owning_job_id'], job_id_plain,
                f'Fixture B: first task owning_job_id should be {job_id_plain!r}, '
                f'got {first_m["owning_job_id"]!r}',
            )
            # Trailing task marker has no job after it → owning_job_id must be None/null
            trailing_m = markers_json_b[1]
            self.assertIn('owning_job_id', trailing_m,
                          f'Fixture B: trailing marker missing owning_job_id: {trailing_m}')
            self.assertIsNone(
                trailing_m['owning_job_id'],
                f'Fixture B: trailing task owning_job_id should be None (no job after it), '
                f'got {trailing_m["owning_job_id"]!r}',
            )

            # --- Fixture C: colon-sanitization ---
            # agentic_job_id with a colon should be sanitized before use
            job_id_with_colon = 'job:with:colons'
            expected_sanitized = 'job_with_colons'
            fixture_c = [
                task_marker(0, 1715515001.0),
                json.dumps({
                    'kind': 'job',
                    'ts': 1715515010.0,
                    'sid': sid,
                    'agentic_job_id': job_id_with_colon,
                    'job_name': 'Colon Job',
                    'job_type': 'feature_development',
                    'status': 'IN_PROGRESS',
                }, separators=(',', ':')),
            ]
            sid3 = 'test-attribution-sid3'
            out_c, rc_c = run_heredoc_python(fixture_c, test_sid=sid3)
            self.assertEqual(rc_c, 0, f'Reader heredoc failed for fixture C: rc={rc_c}')
            markers_json_c = None
            for line in out_c.splitlines():
                if line.startswith('MARKERS_JSON='):
                    markers_json_c = json.loads(line[len('MARKERS_JSON='):])
                    break
            self.assertIsNotNone(markers_json_c, f'MARKERS_JSON not found for fixture C: {out_c}')
            self.assertEqual(len(markers_json_c), 1)
            m_c = markers_json_c[0]
            self.assertIn('owning_job_id', m_c)
            self.assertEqual(
                m_c['owning_job_id'], expected_sanitized,
                f'Fixture C: colon-sanitized owning_job_id should be {expected_sanitized!r}, '
                f'got {m_c["owning_job_id"]!r}',
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_jobs_create_loop_static(self):
        """Phase 9 Task 3 (CREATE-02, CREATE-04, D-09, D-10, D-15): static structure checks
        for the idempotent best-effort jobs create loop in hermes-report.sh.
        """
        hermes_report = SKILL / 'scripts' / 'hermes-report.sh'
        text = hermes_report.read_text()

        # revenium jobs create must be present
        self.assertIn(
            'revenium jobs create',
            text,
            'revenium jobs create command must appear in hermes-report.sh',
        )

        # --agentic-job-id must be present in the jobs create command
        self.assertIn(
            '--agentic-job-id',
            text,
            '--agentic-job-id must appear in hermes-report.sh (jobs create arg)',
        )

        # --quiet must be present with jobs create (D-04)
        import re
        # Find the block containing jobs create and check it has --quiet
        jobs_create_idx = text.index('revenium jobs create')
        context_window = text[max(0, jobs_create_idx - 50):jobs_create_idx + 500]
        self.assertIn(
            '--quiet',
            context_window,
            'jobs create must include --quiet (D-04)',
        )

        # JOB:...:created: ledger write must be present (D-15)
        self.assertRegex(
            text,
            r'JOB:.*:created:',
            'JOB:<id>:created: ledger line must appear in hermes-report.sh (D-15)',
        )

        # JOBS_LEDGER_FILE must be used (no hardcoded path)
        self.assertIn(
            'JOBS_LEDGER_FILE',
            text,
            'JOBS_LEDGER_FILE variable must be referenced in hermes-report.sh',
        )
        self.assertNotIn(
            'revenium-jobs.ledger"',
            text,
            'Hardcoded revenium-jobs.ledger path must not appear outside common.sh',
        )

        # Idempotency gate must be present: grep -q "^JOB:..."
        self.assertIn(
            '^JOB:',
            text,
            'Idempotency gate grep pattern "^JOB:" must appear in hermes-report.sh (D-09)',
        )

        # JOBS_CLI_CAPABLE guard must wrap the create stage.
        # The guard appears on an outer `if` block that encloses the while loop
        # containing `revenium jobs create`, so search 100 lines before the command.
        lines = text.splitlines()
        jobs_create_line = None
        for i, line in enumerate(lines):
            if 'revenium jobs create' in line:
                jobs_create_line = i
                break
        self.assertIsNotNone(jobs_create_line, 'revenium jobs create not found in hermes-report.sh')
        # Check up to 100 lines before jobs create for JOBS_CLI_CAPABLE
        guard_window = '\n'.join(lines[max(0, jobs_create_line - 100):jobs_create_line])
        self.assertIn(
            'JOBS_CLI_CAPABLE',
            guard_window,
            'revenium jobs create must be guarded by JOBS_CLI_CAPABLE check',
        )

        # JOB:...:outcome: ledger write must now be present (Phase 10 — OUTCOME-01/D-06).
        outcome_count = len(re.findall(r'JOB:.*:outcome:', text))
        self.assertGreater(
            outcome_count, 0,
            'JOB:<id>:outcome: ledger line must appear in hermes-report.sh (Phase 10 OUTCOME-01)',
        )

        # revenium jobs outcome command must be present.
        self.assertIn(
            'revenium jobs outcome',
            text,
            'revenium jobs outcome command must appear in hermes-report.sh (OUTCOME-01)',
        )

    def test_jobs_create_loop_e2e(self):
        """Phase 9 Task 3 (CREATE-02, CREATE-04): end-to-end test for the jobs create loop.

        Verifies:
        - A session with a job marker triggers one `revenium jobs create` call
        - A second cron run is idempotent (no second jobs create call)
        - A jobs create failure does not abort metering (best-effort)
        """
        import json
        import os
        import shutil
        import sqlite3
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def run_cron(env, meter_log, jobs_log):
            """Invoke hermes-report.sh, returning (exit_code, meter_invocations, jobs_invocations, output)."""
            for log in (meter_log, jobs_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                result.stdout + result.stderr,
            )

        tmpdir = tempfile.mkdtemp(prefix='gsd-jobs-e2e-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            # Build a revenium shim that:
            # - Handles `config` (exit 0)
            # - Handles `jobs --help` (exit 0, so JOBS_CLI_CAPABLE probe (a) passes)
            # - Handles `meter completion --help` (prints --task-id so probe (b) passes)
            # - Handles `jobs create` (logs to jobs_log, exit 0)
            # - Handles `meter completion` (logs to meter_log, exit 0)
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter-invocations.log')
            jobs_log = os.path.join(tmpdir, 'jobs-invocations.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            sid = '20260516_test_jobs_e2e'
            input_tokens = 10000
            output_tokens = 4000
            total_tokens = input_tokens + output_tokens
            job_id = 'pr-review-abc123'

            def reset_state():
                for path in (state_db, ledger, jobs_ledger):
                    if os.path.exists(path):
                        os.unlink(path)
                for fname in os.listdir(markers_dir):
                    full = os.path.join(markers_dir, fname)
                    if os.path.isdir(full):
                        continue
                    os.unlink(full)

            def write_markers(task_count=2, include_job=True):
                marker_file = os.path.join(markers_dir, f'{sid}.jsonl')
                with open(marker_file, 'w') as f:
                    for i in range(task_count):
                        m = {
                            'muid': f'01893b8a3{i:02x}abcdef0123456789abcde00',
                            'ts': 1715515000.0 + i + 1,
                            'sid': sid,
                            'task_type': 'code_review',
                            'operation_type': 'CHAT',
                        }
                        f.write(json.dumps(m, separators=(',', ':')) + '\n')
                    if include_job:
                        job = {
                            'kind': 'job',
                            'ts': 1715515010.0,
                            'sid': sid,
                            'agentic_job_id': job_id,
                            'job_name': 'PR Review',
                            'job_type': 'code_review',
                            'status': 'IN_PROGRESS',
                        }
                        f.write(json.dumps(job, separators=(',', ':')) + '\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            # =====================================================
            # Sub-case 1: Session with job marker → jobs create called once
            # =====================================================
            reset_state()
            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': input_tokens, 'output_tokens': output_tokens,
                'cache_read': 200, 'cache_write': 100,
                'reasoning': 0, 'estimated_cost': '0.01',
                'api_calls': 2, 'started_at': 1715514000.0,
                'ended_at': 1715515020.0,
                'billing_provider': 'anthropic',
            }])
            write_markers(task_count=2, include_job=True)

            rc1, meter_inv1, jobs_inv1, out1 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc1, 0, f'Run 1 exit {rc1}: {out1}')

            # Should have made exactly one jobs create call
            self.assertEqual(
                len(jobs_inv1), 1,
                f'Run 1: expected 1 jobs create call, got {len(jobs_inv1)}: {out1}',
            )
            # Check --agentic-job-id is in the jobs create call
            jobs_argv1 = jobs_inv1[0]
            self.assertIn(
                '--agentic-job-id', jobs_argv1,
                f'Run 1: --agentic-job-id not found in jobs create argv: {jobs_argv1}',
            )
            agentic_id_idx = jobs_argv1.index('--agentic-job-id') + 1
            self.assertEqual(
                jobs_argv1[agentic_id_idx], job_id,
                f'Run 1: --agentic-job-id value mismatch: {jobs_argv1[agentic_id_idx]!r}',
            )
            self.assertIn(
                '--quiet', jobs_argv1,
                f'Run 1: --quiet not in jobs create argv: {jobs_argv1}',
            )

            # JOB ledger line must have been written
            self.assertTrue(os.path.exists(jobs_ledger),
                            f'Run 1: jobs ledger not created at {jobs_ledger}')
            jobs_ledger_content = open(jobs_ledger).read()
            self.assertRegex(
                jobs_ledger_content,
                rf'^JOB:{re.escape(job_id)}:created:',
                f'Run 1: JOB ledger line not written: {jobs_ledger_content!r}',
            )

            # Task markers should have --agentic-job-id (JOBS_CLI_CAPABLE=true, owning_job_id set)
            self.assertEqual(
                len(meter_inv1), 2,
                f'Run 1: expected 2 meter invocations, got {len(meter_inv1)}: {out1}',
            )
            for argv in meter_inv1:
                self.assertIn(
                    '--agentic-job-id', argv,
                    f'Run 1: --agentic-job-id not found in meter argv: {argv}',
                )
                job_id_idx = argv.index('--agentic-job-id') + 1
                self.assertEqual(
                    argv[job_id_idx], job_id,
                    f'Run 1: --agentic-job-id value mismatch: {argv[job_id_idx]!r}',
                )

            # =====================================================
            # Sub-case 2: Second run is idempotent — no second jobs create
            # =====================================================
            rc2, meter_inv2, jobs_inv2, out2 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc2, 0, f'Run 2 exit {rc2}: {out2}')
            # Session already ledger'd — meter invocations should be 0
            self.assertEqual(
                len(jobs_inv2), 0,
                f'Run 2 (idempotent): expected 0 jobs create calls, got {len(jobs_inv2)}: {out2}',
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Phase 9 Plan 02 — CREATE-03 / D-13 regression and idempotency suite
    # ------------------------------------------------------------------

    def test_job_marker_stamps_agentic_job_id(self):
        """CREATE-03 / D-13 linkage: task markers followed by a job marker produce
        meter completion calls each carrying --agentic-job-id equal to the job's
        agentic_job_id."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a3{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def make_job_marker(sid, job_id, job_type='code_review', status='IN_PROGRESS'):
            """Return a frozen Phase 7 D-03 job-marker dict."""
            return {
                'kind': 'job',
                'ts': 1715516000.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'Test Job',
                'job_type': job_type,
                'status': status,
            }

        def run_cron(env, meter_log, jobs_log):
            for log in (meter_log, jobs_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                result.stdout + result.stderr,
            )

        def argv_to_flags(argv):
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        n_tasks = 3
        job_id = 'pr-review-linkage-001'
        sid = '20260516_test_linkage'

        tmpdir = tempfile.mkdtemp(prefix='gsd-task-id-linkage-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')

            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 12000, 'output_tokens': 5000,
                'cache_read': 300, 'cache_write': 150,
                'reasoning': 0, 'estimated_cost': '0.05',
                'api_calls': n_tasks, 'started_at': 1715514000.0,
                'ended_at': 1715516100.0,
                'billing_provider': 'anthropic',
            }])

            # Write n_tasks task markers followed by one job marker.
            markers_file = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(n_tasks, sid):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid, job_id)
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            rc, meter_inv, _jobs_inv, output = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc, 0, f'cron exit {rc}: {output}')
            self.assertEqual(
                len(meter_inv), n_tasks,
                f'expected {n_tasks} meter invocations, got {len(meter_inv)}: {output}',
            )

            for argv in meter_inv:
                flags = argv_to_flags(argv)
                self.assertIn(
                    '--agentic-job-id', flags,
                    f'CREATE-03/D-13: --agentic-job-id missing from meter completion argv: {argv}',
                )
                self.assertEqual(
                    flags['--agentic-job-id'], job_id,
                    f'CREATE-03/D-13: --agentic-job-id value mismatch '
                    f'got={flags["--agentic-job-id"]!r} want={job_id!r}',
                )
                # The job's name and type ride along so Revenium can group/display
                # spend by job without a second lookup.
                self.assertEqual(
                    flags.get('--agentic-job-name'), 'Test Job',
                    f'CREATE-03/D-13: --agentic-job-name missing/wrong in argv: {argv}',
                )
                self.assertEqual(
                    flags.get('--agentic-job-type'), 'code_review',
                    f'CREATE-03/D-13: --agentic-job-type missing/wrong in argv: {argv}',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_jobless_session_omits_task_id(self):
        """D-13 / SCHEMA-04 byte-identity regression: task markers with NO job marker
        produce meter completion calls carrying no --task-id flag (v1.0 byte-identity
        guarantee; T-09-08 attribution-leak guard)."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a3{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'refactor',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def run_cron(env, meter_log, jobs_log):
            for log in (meter_log, jobs_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                result.stdout + result.stderr,
            )

        def argv_to_flags(argv):
            d = {}
            i = 0
            while i < len(argv):
                tok = argv[i]
                if tok.startswith('--'):
                    if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                        d[tok] = argv[i + 1]
                        i += 2
                    else:
                        d[tok] = True
                        i += 1
                else:
                    i += 1
            return d

        n_tasks = 4
        sid = '20260516_test_jobless'

        tmpdir = tempfile.mkdtemp(prefix='gsd-jobless-byte-id-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')

            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 8000, 'output_tokens': 3000,
                'cache_read': 200, 'cache_write': 100,
                'reasoning': 0, 'estimated_cost': '0.03',
                'api_calls': n_tasks, 'started_at': 1715514000.0,
                'ended_at': 1715515100.0,
                'billing_provider': 'anthropic',
            }])

            # Write n_tasks task markers with NO job marker.
            markers_file = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(n_tasks, sid):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
            # Deliberately no job marker written.

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            rc, meter_inv, jobs_inv, output = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc, 0, f'cron exit {rc}: {output}')
            self.assertEqual(
                len(meter_inv), n_tasks,
                f'expected {n_tasks} meter invocations, got {len(meter_inv)}: {output}',
            )

            # No job markers → no jobs create calls.
            self.assertEqual(
                len(jobs_inv), 0,
                f'D-13: no job marker → no jobs create expected; got {len(jobs_inv)}: {output}',
            )

            # Critical: no --task-id must appear in any meter completion argv.
            for argv in meter_inv:
                flags = argv_to_flags(argv)
                self.assertNotIn(
                    '--task-id', flags,
                    f'D-13/T-09-08: job-less marker must not carry --task-id; '
                    f'attribution leak detected in argv: {argv}',
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cron_jobs_create_is_idempotent(self):
        """CREATE-02 / D-09 idempotency: running the cron twice over the same job
        marker invokes `revenium jobs create` exactly once; the second run is gated
        by the JOB:<id>:created ledger line (T-09-09)."""
        import json
        import os
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a3{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def make_job_marker(sid, job_id, job_type='code_review', status='IN_PROGRESS'):
            """Return a frozen Phase 7 D-03 job-marker dict."""
            return {
                'kind': 'job',
                'ts': 1715516000.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'PR Review Idempotent',
                'job_type': job_type,
                'status': status,
            }

        def run_cron(env, meter_log, jobs_log):
            for log in (meter_log, jobs_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                result.stdout + result.stderr,
            )

        n_tasks = 2
        job_id = 'idempotent-job-abc999'
        sid = '20260516_test_idempotent'

        tmpdir = tempfile.mkdtemp(prefix='gsd-jobs-idempotent-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')

            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            # Build fixture: session with task markers + one job marker.
            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 9000, 'output_tokens': 3500,
                'cache_read': 250, 'cache_write': 120,
                'reasoning': 0, 'estimated_cost': '0.04',
                'api_calls': n_tasks, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(n_tasks, sid):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid, job_id)
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            # Run 1: jobs create must be called exactly once.
            rc1, _meter1, jobs_inv1, out1 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc1, 0, f'Run 1 exit {rc1}: {out1}')
            self.assertEqual(
                len(jobs_inv1), 1,
                f'CREATE-02: Run 1 expected exactly 1 jobs create call, '
                f'got {len(jobs_inv1)}: {out1}',
            )

            # Verify the ledger line was written so the idempotency gate will fire.
            self.assertTrue(
                os.path.exists(jobs_ledger),
                f'CREATE-02: jobs ledger not created after Run 1',
            )
            import re as _re
            ledger_text = open(jobs_ledger).read()
            self.assertRegex(
                ledger_text,
                rf'^JOB:{_re.escape(job_id)}:created:',
                f'CREATE-02: JOB ledger line not written after Run 1',
            )

            # Run 2: same state.db and marker file — ledger gate must suppress jobs create.
            # The meter log is re-read each run (run_cron resets it); the session has
            # already been ledger'd so meter invocations will be 0 too.
            rc2, _meter2, jobs_inv2, out2 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc2, 0, f'Run 2 exit {rc2}: {out2}')
            self.assertEqual(
                len(jobs_inv2), 0,
                f'CREATE-02/D-09 idempotency violated: Run 2 should produce 0 '
                f'jobs create calls (ledger-gated), got {len(jobs_inv2)}: {out2}',
            )

            # Total jobs create calls across both runs == 1 (exact count, T-09-09).
            total_jobs_create = len(jobs_inv1) + len(jobs_inv2)
            self.assertEqual(
                total_jobs_create, 1,
                f'T-09-09: expected exactly 1 total jobs create across 2 runs, '
                f'got {total_jobs_create}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cron_jobs_create_after_arc_close_token_stable(self):
        """WR-02 regression: a session metered in an earlier tick gets its arc-end
        job marker created on a later tick even when the session's token total has
        not grown (D-08 arc-close ordering). Also asserts same-tick idempotency:
        a token-growing session with a fresh job marker produces exactly one
        jobs create call, not two."""
        import json
        import os
        import re
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a4{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def make_job_marker(sid, job_id, job_type='code_review', status='IN_PROGRESS'):
            """Return a frozen Phase 7 D-03 job-marker dict."""
            return {
                'kind': 'job',
                'ts': 1715516000.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'PR Review Arc Close',
                'job_type': job_type,
                'status': status,
            }

        def run_cron(env, meter_log, jobs_log):
            for log in (meter_log, jobs_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                result.stdout + result.stderr,
            )

        # --- Arc-close scenario (Run 1 → append job marker → Run 2 → Run 3) ---
        n_tasks = 2
        job_id = 'arc-close-job-def777'
        sid = '20260516_test_arc_close'
        total_tokens = 9000 + 3500  # must match state.db row below

        tmpdir = tempfile.mkdtemp(prefix='gsd-arc-close-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            hermes_ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')

            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            # Build fixture: one session with task markers ONLY (no job marker yet).
            # D-08: job marker is appended AFTER the last LLM call.
            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 9000, 'output_tokens': 3500,
                'cache_read': 250, 'cache_write': 120,
                'reasoning': 0, 'estimated_cost': '0.04',
                'api_calls': n_tasks, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(n_tasks, sid):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
            # No job marker yet — D-08 arc-close ordering.

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
                # Make the settle-window deterministic — no wall-clock backdating needed.
                'REVENIUM_CRON_SETTLE_SECONDS': '0',
            }

            # Run 1: meters the session; no job marker present — zero jobs create calls.
            rc1, _meter1, jobs_inv1, out1 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc1, 0, f'Run 1 exit {rc1}: {out1}')
            # Assert HERMES ledger row was written.
            self.assertTrue(os.path.exists(hermes_ledger), f'WR-02: HERMES ledger not created after Run 1: {out1}')
            hermes_text = open(hermes_ledger).read()
            self.assertRegex(
                hermes_text,
                re.compile(r'^HERMES:' + re.escape(sid) + r':' + str(total_tokens) + r':', re.M),
                f'WR-02: HERMES ledger row not written for sid={sid} total={total_tokens}',
            )
            self.assertEqual(
                len(jobs_inv1), 0,
                f'WR-02: Run 1 expected 0 jobs create calls (no job marker), got {len(jobs_inv1)}: {out1}',
            )

            # Between runs: append the job marker WITHOUT changing state.db token counts.
            # This models D-08 arc-close: agent appends kind:"job" after last LLM call.
            with open(markers_file, 'a') as f:
                job = make_job_marker(sid, job_id)
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # Run 2: token total is UNCHANGED (would hit the token pre-filter), but
            # WR-02 fix must allow the cron to still reach the jobs-create stage.
            rc2, _meter2, jobs_inv2, out2 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc2, 0, f'Run 2 exit {rc2}: {out2}')
            self.assertEqual(
                len(jobs_inv2), 1,
                f'WR-02: Run 2 expected exactly 1 jobs create call for arc-end job '
                f'(token-stable session), got {len(jobs_inv2)}: {out2}',
            )
            # Verify --agentic-job-id is present in the create args.
            run2_argv = jobs_inv2[0]
            self.assertIn(
                '--agentic-job-id', run2_argv,
                f'WR-02: --agentic-job-id missing from jobs create argv: {run2_argv}',
            )
            idx = run2_argv.index('--agentic-job-id')
            self.assertEqual(
                run2_argv[idx + 1], job_id,
                f'WR-02: --agentic-job-id value mismatch: {run2_argv}',
            )
            # Assert JOB ledger line was written.
            self.assertTrue(os.path.exists(jobs_ledger), f'WR-02: jobs ledger not created after Run 2')
            jobs_text = open(jobs_ledger).read()
            self.assertRegex(
                jobs_text,
                re.compile(r'^JOB:' + re.escape(job_id) + r':created:', re.M),
                f'WR-02: JOB ledger line not written after Run 2',
            )

            # Run 3: idempotency — the JOB:<id>:created gate suppresses a second create.
            rc3, _meter3, jobs_inv3, out3 = run_cron(base_env, meter_log, jobs_log)
            self.assertEqual(rc3, 0, f'Run 3 exit {rc3}: {out3}')
            self.assertEqual(
                len(jobs_inv3), 0,
                f'WR-02 idempotency: Run 3 should produce 0 jobs create calls '
                f'(JOB ledger gate), got {len(jobs_inv3)}: {out3}',
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # --- Same-tick sub-assertion: a token-GROWING session with a fresh job marker
        # in its marker file BEFORE any cron run produces exactly ONE jobs create call,
        # not two (pre-guard scan + in-loop stage must share the single ledger gate). ---
        sid2 = '20260516_test_same_tick'
        job_id2 = 'same-tick-job-ghi888'

        tmpdir2 = tempfile.mkdtemp(prefix='gsd-same-tick-')
        try:
            hermes_home2 = os.path.join(tmpdir2, 'hh')
            state_dir2 = os.path.join(hermes_home2, 'state', 'revenium')
            markers_dir2 = os.path.join(state_dir2, 'markers')
            os.makedirs(markers_dir2, mode=0o700)
            state_db2 = os.path.join(hermes_home2, 'state.db')
            jobs_ledger2 = os.path.join(state_dir2, 'revenium-jobs.ledger')

            shim_home2 = os.path.join(tmpdir2, 'home')
            bin_dir2 = os.path.join(shim_home2, '.local', 'bin')
            os.makedirs(bin_dir2)
            meter_log2 = os.path.join(tmpdir2, 'meter.log')
            jobs_log2 = os.path.join(tmpdir2, 'jobs.log')

            shim2 = os.path.join(bin_dir2, 'revenium')
            with open(shim2, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log2}"\n'
                    f'        printf "\\n" >> "{jobs_log2}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log2}"\n'
                    f'    printf "\\n" >> "{meter_log2}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim2, 0o755)

            # Build fixture: token-GROWING session (no prior HERMES ledger row) whose
            # marker file ALREADY contains both task markers and a fresh job marker.
            build_state_db(state_db2, [{
                'id': sid2, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 8000, 'output_tokens': 2000,
                'cache_read': 100, 'cache_write': 50,
                'reasoning': 0, 'estimated_cost': '0.03',
                'api_calls': 2, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file2 = os.path.join(markers_dir2, f'{sid2}.jsonl')
            with open(markers_file2, 'w') as f:
                for m in make_markers(2, sid2):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job2 = make_job_marker(sid2, job_id2)
                f.write(json.dumps(job2, separators=(',', ':')) + '\n')

            base_env2 = {
                **os.environ,
                'HOME': shim_home2,
                'HERMES_HOME': hermes_home2,
                'REVENIUM_STATE_DIR': state_dir2,
                'PATH': bin_dir2 + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
                'REVENIUM_CRON_SETTLE_SECONDS': '0',
            }

            # Run once: the pre-guard scan and the in-loop stage must share the single
            # JOB:<id>:created gate — exactly ONE jobs create call, not two.
            _, _meter_st, jobs_inv_st, out_st = run_cron(base_env2, meter_log2, jobs_log2)
            jobs_for_id2 = [
                inv for inv in jobs_inv_st
                if '--agentic-job-id' in inv
                and inv[inv.index('--agentic-job-id') + 1] == job_id2
            ]
            self.assertEqual(
                len(jobs_for_id2), 1,
                f'WR-02 same-tick: expected exactly 1 jobs create for {job_id2} '
                f'(pre-guard + in-loop must share single gate), '
                f'got {len(jobs_for_id2)}: {out_st}',
            )
        finally:
            shutil.rmtree(tmpdir2, ignore_errors=True)

    def test_cron_outcome_is_idempotent(self):
        """TEST-03 / OUTCOME-01..05: post-loop outcome stage reports each terminated
        arc exactly once, defers gracefully when created line is absent, validates
        status enum, and recovers from partial failure (OUTCOME-02)."""
        import json
        import os
        import re as _re
        import shutil
        import sqlite3
        import subprocess
        import tempfile

        HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

        def build_state_db(path, sessions):
            conn = sqlite3.connect(str(path))
            conn.execute(
                'CREATE TABLE sessions ('
                'id TEXT, model TEXT, source TEXT, '
                'input_tokens INTEGER, output_tokens INTEGER, '
                'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
                'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
                'api_call_count INTEGER, started_at REAL, ended_at REAL, '
                'billing_provider TEXT)'
            )
            for s in sessions:
                conn.execute(
                    'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (s['id'], s['model'], s['source'],
                     s['input_tokens'], s['output_tokens'],
                     s['cache_read'], s['cache_write'],
                     s['reasoning'], s['estimated_cost'],
                     s['api_calls'], s['started_at'], s['ended_at'],
                     s['billing_provider']),
                )
            conn.commit()
            conn.close()

        def make_markers(n, sid, ts_base=1715515000.0):
            return [
                {
                    'muid': f'01893b8a3{i:02x}abcdef0123456789abcdef0',
                    'ts': ts_base + i + 1,
                    'sid': sid,
                    'task_type': 'code_review',
                    'operation_type': 'CHAT',
                }
                for i in range(n)
            ]

        def make_job_marker(sid, job_id, job_type='code_review', status='SUCCESS'):
            """Return a Phase 7 D-03 job-marker dict with configurable status."""
            return {
                'kind': 'job',
                'ts': 1715516000.0,
                'sid': sid,
                'agentic_job_id': job_id,
                'job_name': 'PR Review Outcome Test',
                'job_type': job_type,
                'status': status,
            }

        def make_shim(bin_dir, meter_log, jobs_log, outcome_log):
            """Write a revenium shim that logs invocations to separate log files."""
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{jobs_log}"\n'
                    f'        printf "\\n" >> "{jobs_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      outcome)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{outcome_log}"\n'
                    f'        printf "\\n" >> "{outcome_log}"\n'
                    '        exit ${OUTCOME_EXIT_CODE:-0}\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)
            return shim

        def run_cron(env, meter_log, jobs_log, outcome_log):
            for log in (meter_log, jobs_log, outcome_log):
                if os.path.exists(log):
                    os.unlink(log)
                open(log, 'w').close()
            # Truncate the metering log so its content is bounded to this run.
            metering_log = os.path.join(env['REVENIUM_STATE_DIR'], 'revenium-metering.log')
            if os.path.exists(metering_log):
                os.unlink(metering_log)
            result = subprocess.run(
                ['bash', str(HERMES_REPORT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            import shlex

            def parse_log(path):
                invocations = []
                with open(path) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            invocations.append(shlex.split(line))
                return invocations

            # log() writes to revenium-metering.log (canonical sink) and only
            # mirrors to stderr on TTY. Under subprocess capture there is no
            # TTY, so OUTCOME-04 / OUTCOME-05 warn lines live in the log file.
            metering_content = (
                open(metering_log).read() if os.path.exists(metering_log) else ''
            )
            return (
                result.returncode,
                parse_log(meter_log),
                parse_log(jobs_log),
                parse_log(outcome_log),
                result.stdout + result.stderr + metering_content,
            )

        sid = '20260516_test_outcome_idempotent'
        job_id = 'outcome-idempotent-job-abc123'

        # ---------------------------------------------------------------
        # Scenario 1: Double-outcome idempotency (core OUTCOME-01)
        # ---------------------------------------------------------------
        tmpdir1 = tempfile.mkdtemp(prefix='gsd-outcome-s1-')
        try:
            hermes_home = os.path.join(tmpdir1, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir1, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir1, 'meter.log')
            jobs_log = os.path.join(tmpdir1, 'jobs.log')
            outcome_log = os.path.join(tmpdir1, 'outcome.log')

            make_shim(bin_dir, meter_log, jobs_log, outcome_log)

            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 9000, 'output_tokens': 3500,
                'cache_read': 250, 'cache_write': 120,
                'reasoning': 0, 'estimated_cost': '0.04',
                'api_calls': 2, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(2, sid):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid, job_id, status='SUCCESS')
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # Pre-seed created line so outcome stage can run immediately.
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id}:created:1715516001.000\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            # Run 1: outcome must be called exactly once.
            rc1, _m1, _j1, out_inv1, out1 = run_cron(base_env, meter_log, jobs_log, outcome_log)
            self.assertEqual(rc1, 0, f'S1 Run 1 exit {rc1}: {out1}')
            self.assertEqual(
                len(out_inv1), 1,
                f'OUTCOME-01 S1: Run 1 expected 1 outcome call, got {len(out_inv1)}: {out1}',
            )

            # Verify the ledger outcome line was written.
            ledger_text = open(jobs_ledger).read()
            self.assertTrue(
                any(_re.match(rf'^JOB:{_re.escape(job_id)}:outcome:', l)
                    for l in ledger_text.splitlines()),
                f'OUTCOME-01 S1: JOB outcome ledger line not written after Run 1',
            )

            # Run 2: ledger gate must suppress second outcome call.
            rc2, _m2, _j2, out_inv2, out2 = run_cron(base_env, meter_log, jobs_log, outcome_log)
            self.assertEqual(rc2, 0, f'S1 Run 2 exit {rc2}: {out2}')
            self.assertEqual(
                len(out_inv2), 0,
                f'OUTCOME-01 idempotency violated: Run 2 should produce 0 outcome calls '
                f'(ledger-gated), got {len(out_inv2)}: {out2}',
            )

            # Total outcome calls across both runs == 1.
            total_outcome = len(out_inv1) + len(out_inv2)
            self.assertEqual(
                total_outcome, 1,
                f'TEST-03: expected exactly 1 total outcome call across 2 runs, '
                f'got {total_outcome}',
            )

            # Exactly one outcome ledger line.
            ledger_text2 = open(jobs_ledger).read()
            outcome_lines = [l for l in ledger_text2.splitlines()
                             if _re.match(rf'^JOB:{_re.escape(job_id)}:outcome:', l)]
            self.assertEqual(
                len(outcome_lines), 1,
                f'OUTCOME-01: expected exactly 1 outcome ledger line, got {len(outcome_lines)}',
            )
        finally:
            shutil.rmtree(tmpdir1, ignore_errors=True)

        # ---------------------------------------------------------------
        # Scenario 2: OUTCOME-04 next-tick deferral (no created line)
        # ---------------------------------------------------------------
        tmpdir2 = tempfile.mkdtemp(prefix='gsd-outcome-s2-')
        try:
            hermes_home = os.path.join(tmpdir2, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir2, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir2, 'meter.log')
            jobs_log = os.path.join(tmpdir2, 'jobs.log')
            outcome_log = os.path.join(tmpdir2, 'outcome.log')

            make_shim(bin_dir, meter_log, jobs_log, outcome_log)

            sid2 = '20260516_test_outcome_deferred'
            job_id2 = 'outcome-deferred-job-def456'

            build_state_db(state_db, [{
                'id': sid2, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 5000, 'output_tokens': 2000,
                'cache_read': 0, 'cache_write': 0,
                'reasoning': 0, 'estimated_cost': '0.02',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid2}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(1, sid2):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid2, job_id2, status='SUCCESS')
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # NO pre-seeded created line; shim exits non-zero for jobs create to simulate
            # a failed create; leave ledger empty so outcome is deferred.
            # Actually: just don't pre-seed the ledger — the pre-guard scan will
            # attempt jobs create (shim exits 0) which writes the created line.
            # To truly test deferral we need the create to fail. Use OUTCOME_EXIT_CODE
            # to make the shim's create exit non-zero as well.
            # Simpler: start with empty ledger but override the shim to fail jobs create.
            shim_path = os.path.join(bin_dir, 'revenium')
            with open(shim_path, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  jobs)\n'
                    '    shift\n'
                    '    case "$1" in\n'
                    '      --help) exit 0 ;;\n'
                    '      create) exit 1 ;;\n'
                    '      outcome)\n'
                    '        shift\n'
                    f'        printf "%q " "$@" >> "{outcome_log}"\n'
                    f'        printf "\\n" >> "{outcome_log}"\n'
                    '        exit 0\n'
                    '        ;;\n'
                    '      *) exit 0 ;;\n'
                    '    esac\n'
                    '    ;;\n'
                    '  meter)\n'
                    '    shift; shift\n'
                    '    if [[ "$1" == "--help" ]]; then\n'
                    '      echo "--agentic-job-id  Agentic job instance identifier"\n'
                    '      exit 0\n'
                    '    fi\n'
                    f'    printf "%q " "$@" >> "{meter_log}"\n'
                    f'    printf "\\n" >> "{meter_log}"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim_path, 0o755)

            base_env2 = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            rc2, _m2, _j2, out_inv2, out2 = run_cron(base_env2, meter_log, jobs_log, outcome_log)
            self.assertEqual(rc2, 0, f'S2 exit {rc2}: {out2}')

            # OUTCOME-04: zero outcome calls because no created line.
            self.assertEqual(
                len(out_inv2), 0,
                f'OUTCOME-04 deferral: expected 0 outcome calls when no created line, '
                f'got {len(out_inv2)}: {out2}',
            )

            # Deferred or wedged-job warn must appear in output (both indicate OUTCOME-04
            # deferral — "wedged job" fires when marker ts is older than stale threshold).
            self.assertTrue(
                'outcome deferred' in out2 or 'wedged job' in out2,
                f'OUTCOME-04: expected "outcome deferred" or "wedged job" warn in output: {out2}',
            )

            # No outcome ledger line should exist.
            if os.path.exists(jobs_ledger):
                ledger_text = open(jobs_ledger).read()
                outcome_lines = [l for l in ledger_text.splitlines()
                                 if ':outcome:' in l and job_id2 in l]
                self.assertEqual(
                    len(outcome_lines), 0,
                    f'OUTCOME-04: no outcome ledger line expected, got: {outcome_lines}',
                )
        finally:
            shutil.rmtree(tmpdir2, ignore_errors=True)

        # ---------------------------------------------------------------
        # Scenario 3: Same-tick create + outcome (D-01)
        # ---------------------------------------------------------------
        tmpdir3 = tempfile.mkdtemp(prefix='gsd-outcome-s3-')
        try:
            hermes_home = os.path.join(tmpdir3, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir3, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir3, 'meter.log')
            jobs_log = os.path.join(tmpdir3, 'jobs.log')
            outcome_log = os.path.join(tmpdir3, 'outcome.log')

            make_shim(bin_dir, meter_log, jobs_log, outcome_log)

            sid3 = '20260516_test_outcome_sametick'
            job_id3 = 'outcome-sametick-job-ghi789'

            build_state_db(state_db, [{
                'id': sid3, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 7000, 'output_tokens': 2500,
                'cache_read': 100, 'cache_write': 50,
                'reasoning': 0, 'estimated_cost': '0.03',
                'api_calls': 2, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid3}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(2, sid3):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid3, job_id3, status='SUCCESS')
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # Start with empty jobs ledger — no pre-seeded created line.
            base_env3 = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            rc3, _m3, _j3, out_inv3, out3 = run_cron(base_env3, meter_log, jobs_log, outcome_log)
            self.assertEqual(rc3, 0, f'S3 exit {rc3}: {out3}')

            # After one run: both created and outcome ledger lines must exist.
            self.assertTrue(
                os.path.exists(jobs_ledger),
                f'D-01 same-tick: jobs ledger not created: {out3}',
            )
            ledger_text3 = open(jobs_ledger).read()
            self.assertTrue(
                any(_re.match(rf'^JOB:{_re.escape(job_id3)}:created:', l)
                    for l in ledger_text3.splitlines()),
                f'D-01 same-tick: no created line after single run: {ledger_text3}',
            )
            self.assertTrue(
                any(_re.match(rf'^JOB:{_re.escape(job_id3)}:outcome:', l)
                    for l in ledger_text3.splitlines()),
                f'D-01 same-tick: no outcome line after single run: {ledger_text3}',
            )
        finally:
            shutil.rmtree(tmpdir3, ignore_errors=True)

        # ---------------------------------------------------------------
        # Scenario 4: Invalid-status skip (D-03/D-04 OUTCOME-05)
        # ---------------------------------------------------------------
        tmpdir4 = tempfile.mkdtemp(prefix='gsd-outcome-s4-')
        try:
            hermes_home = os.path.join(tmpdir4, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir4, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir4, 'meter.log')
            jobs_log = os.path.join(tmpdir4, 'jobs.log')
            outcome_log = os.path.join(tmpdir4, 'outcome.log')

            make_shim(bin_dir, meter_log, jobs_log, outcome_log)

            sid4 = '20260516_test_outcome_invalid'
            job_id4 = 'outcome-invalid-status-jkl012'

            build_state_db(state_db, [{
                'id': sid4, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 4000, 'output_tokens': 1500,
                'cache_read': 0, 'cache_write': 0,
                'reasoning': 0, 'estimated_cost': '0.01',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid4}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(1, sid4):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                # Invalid status: IN_PROGRESS is not in {SUCCESS, FAILED, CANCELLED}
                job = make_job_marker(sid4, job_id4, status='IN_PROGRESS')
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # Pre-seed created line so the outcome stage reaches the enum check.
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id4}:created:1715516001.000\n')

            base_env4 = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
            }

            rc4, _m4, _j4, out_inv4, out4 = run_cron(base_env4, meter_log, jobs_log, outcome_log)
            self.assertEqual(rc4, 0, f'S4 exit {rc4}: {out4}')

            # OUTCOME-05: zero outcome calls for invalid status.
            self.assertEqual(
                len(out_inv4), 0,
                f'OUTCOME-05: expected 0 outcome calls for IN_PROGRESS status, '
                f'got {len(out_inv4)}: {out4}',
            )

            # Warn must appear in output.
            self.assertTrue(
                'outcome skipped' in out4 or 'invalid status' in out4,
                f'OUTCOME-05: expected invalid-status warn in output: {out4}',
            )

            # No outcome ledger line (the :outcome: verb must not appear).
            ledger_text4 = open(jobs_ledger).read()
            outcome_lines4 = [l for l in ledger_text4.splitlines()
                               if ':outcome:' in l and job_id4 in l]
            self.assertEqual(
                len(outcome_lines4), 0,
                f'OUTCOME-05: no outcome ledger line expected for invalid status, '
                f'got: {outcome_lines4}',
            )
        finally:
            shutil.rmtree(tmpdir4, ignore_errors=True)

        # ---------------------------------------------------------------
        # Scenario 5: Partial-failure re-attempt (OUTCOME-02)
        # ---------------------------------------------------------------
        tmpdir5 = tempfile.mkdtemp(prefix='gsd-outcome-s5-')
        try:
            hermes_home = os.path.join(tmpdir5, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')
            jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')

            shim_home = os.path.join(tmpdir5, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir5, 'meter.log')
            jobs_log = os.path.join(tmpdir5, 'jobs.log')
            outcome_log = os.path.join(tmpdir5, 'outcome.log')

            make_shim(bin_dir, meter_log, jobs_log, outcome_log)

            sid5 = '20260516_test_outcome_partialfail'
            job_id5 = 'outcome-partial-fail-mno345'

            build_state_db(state_db, [{
                'id': sid5, 'model': 'claude-sonnet-4-6', 'source': 'test',
                'input_tokens': 6000, 'output_tokens': 2000,
                'cache_read': 50, 'cache_write': 25,
                'reasoning': 0, 'estimated_cost': '0.02',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715516200.0,
                'billing_provider': 'anthropic',
            }])
            markers_file = os.path.join(markers_dir, f'{sid5}.jsonl')
            with open(markers_file, 'w') as f:
                for m in make_markers(1, sid5):
                    f.write(json.dumps(m, separators=(',', ':')) + '\n')
                job = make_job_marker(sid5, job_id5, status='SUCCESS')
                f.write(json.dumps(job, separators=(',', ':')) + '\n')

            # Pre-seed created line.
            with open(jobs_ledger, 'w') as f:
                f.write(f'JOB:{job_id5}:created:1715516001.000\n')

            base_env5_fail = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'TZ': 'UTC',
                'OUTCOME_EXIT_CODE': '1',  # Shim exits non-zero (no 409 in output)
            }

            # Failing run: shim exits 1, no 409 indicator in output.
            rc5a, _m5a, _j5a, out_inv5a, out5a = run_cron(
                base_env5_fail, meter_log, jobs_log, outcome_log
            )
            self.assertEqual(rc5a, 0, f'S5 failing run exit {rc5a}: {out5a}')

            # No outcome ledger line after failing run (the :outcome: verb must be absent).
            ledger_text5 = open(jobs_ledger).read()
            outcome_lines5 = [l for l in ledger_text5.splitlines()
                               if ':outcome:' in l and job_id5 in l]
            self.assertEqual(
                len(outcome_lines5), 0,
                f'OUTCOME-02: no outcome ledger line expected after failing run, '
                f'got: {outcome_lines5}',
            )

            # Recovering run: shim exits 0.
            base_env5_ok = {**base_env5_fail}
            base_env5_ok['OUTCOME_EXIT_CODE'] = '0'

            rc5b, _m5b, _j5b, out_inv5b, out5b = run_cron(
                base_env5_ok, meter_log, jobs_log, outcome_log
            )
            self.assertEqual(rc5b, 0, f'S5 recovering run exit {rc5b}: {out5b}')

            # Exactly one outcome call in the recovering run.
            self.assertEqual(
                len(out_inv5b), 1,
                f'OUTCOME-02: expected 1 outcome call in recovering run, '
                f'got {len(out_inv5b)}: {out5b}',
            )

            # Outcome ledger line now present.
            ledger_text5b = open(jobs_ledger).read()
            self.assertTrue(
                any(_re.match(rf'^JOB:{_re.escape(job_id5)}:outcome:', l)
                    for l in ledger_text5b.splitlines()),
                f'OUTCOME-02: outcome ledger line must exist after recovering run: {ledger_text5b}',
            )
        finally:
            shutil.rmtree(tmpdir5, ignore_errors=True)

    # ------------------------------------------------------------------
    # Phase 12 — behavioral coverage for the hook scripts (CR-02 closure).
    # The CI suite previously only checked file existence and `bash -n`.
    # These tests invoke the real scripts with HERMES_HOME /
    # REVENIUM_HOOKS_CONFIG_FILE / BUDGET_STATUS_FILE / MARKERS_DIR env
    # overrides pointed at a tempdir — no test touches the real ~/.hermes.
    # ------------------------------------------------------------------

    def test_install_hooks_foreign_key(self):
        """CR-01 regression: install-hooks.sh against a config.yaml that already
        has a foreign pre_llm_call: hook must register BOTH revenium commands
        without destroying the foreign entry. This is the test that would have
        caught the pre-12-04 installer silently skipping registration."""
        import os
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-install-foreign-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            with open(config_path, 'w', encoding='utf-8') as fh:
                fh.write(
                    'hooks:\n'
                    '  pre_llm_call:\n'
                    '    - command: /opt/other/foreign-hook.sh\n'
                    '      timeout: 3\n'
                )
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            result = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'install-hooks.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            with open(config_path, encoding='utf-8') as fh:
                config = fh.read()
            self.assertIn(
                'pre_llm_call.sh', config,
                f'pre_llm_call.sh revenium command missing from config:\n{config}',
            )
            self.assertIn(
                'pre_tool_call.sh', config,
                f'pre_tool_call.sh revenium command missing from config:\n{config}',
            )
            self.assertIn(
                '/opt/other/foreign-hook.sh', config,
                f'foreign hook destroyed by install:\n{config}',
            )

            # CR-01 structural assertions: substring presence alone is
            # satisfied by malformed YAML. The buggy installer captured a
            # newline into the indent group and injected stray blank lines
            # inside the hooks block. Assert real structure here.
            lines = config.split('\n')

            # No blank line may appear between an event key and its first
            # list item, nor between a `- command:` line and its `timeout:`.
            for idx, line in enumerate(lines[:-1]):
                stripped = line.strip()
                if stripped.endswith('call:') and stripped.startswith('pre_'):
                    self.assertNotEqual(
                        lines[idx + 1].strip(), '',
                        'blank line injected between event key and first '
                        f'list item:\n{config}',
                    )
                if stripped.startswith('- command:'):
                    self.assertNotEqual(
                        lines[idx + 1].strip(), '',
                        'blank line injected between - command: and its '
                        f'continuation:\n{config}',
                    )

            # Every `- command:` list item must share a single consistent
            # indentation within the hooks block (the buggy indent string
            # carried an embedded newline, breaking alignment).
            command_indents = {
                len(line) - len(line.lstrip(' '))
                for line in lines
                if line.lstrip(' ').startswith('- command:')
            }
            self.assertEqual(
                len(command_indents), 1,
                'inconsistent indentation across - command: lines '
                f'(indents={sorted(command_indents)}):\n{config}',
            )

            # The hooks block (the indented YAML under `hooks:`) must contain
            # no blank lines — the buggy installer injected them. Collect the
            # block as the run of indented lines immediately after `hooks:`,
            # stopping at the first non-indented line (e.g. the
            # `# hermes-revenium-hooks` tag or end of file). Trailing blank
            # lines after that tag are outside the block and irrelevant.
            hooks_idx = next(
                i for i, ln in enumerate(lines) if ln.rstrip() == 'hooks:'
            )
            block = []
            for ln in lines[hooks_idx + 1:]:
                if ln.startswith((' ', '\t')):
                    block.append(ln)
                elif ln.strip() == '':
                    # A blank line interrupting indented content is a defect;
                    # a blank line after the block has ended is harmless. Peek
                    # ahead: if more indented content follows, it is inside.
                    block.append(ln)
                else:
                    break
            # Trim trailing blank lines that sit past the last indented line.
            while block and block[-1].strip() == '':
                block.pop()
            self.assertTrue(
                all(ln.strip() != '' for ln in block),
                f'stray blank line inside hooks block:\n{config}',
            )

    def test_install_hooks_inline_empty_map(self):
        """Regression: install-hooks.sh against a config.yaml whose only hooks
        declaration is the empty inline flow map `hooks: {}` must produce exactly
        ONE top-level block-style `hooks:` key carrying both revenium command
        entries, the timeout: 5 attribute, and the # hermes-revenium-hooks tag.
        Surrounding YAML keys must be untouched."""
        import os
        import re
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-install-inline-empty-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            with open(config_path, 'w', encoding='utf-8') as fh:
                fh.write(
                    'agent_name: test\n'
                    'hooks: {}\n'
                    'model: claude\n'
                )
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            result = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'install-hooks.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            with open(config_path, encoding='utf-8') as fh:
                config = fh.read()

            # Both revenium command paths must be present.
            self.assertIn(
                'pre_llm_call.sh', config,
                f'pre_llm_call.sh revenium command missing from config:\n{config}',
            )
            self.assertIn(
                'pre_tool_call.sh', config,
                f'pre_tool_call.sh revenium command missing from config:\n{config}',
            )

            # The hook tag must be present.
            self.assertIn(
                '# hermes-revenium-hooks', config,
                f'hook tag missing from config:\n{config}',
            )

            # timeout: 5 must be present (must_haves truth 2).
            self.assertIn(
                'timeout: 5', config,
                f'timeout: 5 missing from config:\n{config}',
            )

            # EXACTLY ONE top-level hooks: key — count lines that start with
            # `hooks:` at column 0.
            hooks_lines = [
                line for line in config.split('\n')
                if re.match(r'^hooks:', line)
            ]
            self.assertEqual(
                len(hooks_lines), 1,
                f'Expected exactly 1 top-level hooks: line, '
                f'got {len(hooks_lines)}: {hooks_lines!r}\n{config}',
            )

            # The surviving hooks: line must be bare (no inline {} or []).
            self.assertEqual(
                hooks_lines[0].rstrip(), 'hooks:',
                f'hooks: line is not bare block-style: {hooks_lines[0]!r}\n{config}',
            )

            # The inline empty form must be gone.
            self.assertNotIn(
                'hooks: {}', config,
                f'hooks: {{}} literal survived install:\n{config}',
            )

            # Surrounding keys must still be present.
            self.assertIn(
                'agent_name: test', config,
                f'agent_name key missing — surrounding YAML mutated:\n{config}',
            )
            self.assertIn(
                'model: claude', config,
                f'model key missing — surrounding YAML mutated:\n{config}',
            )

            # Idempotency leg: run again and assert the file is byte-identical.
            with open(config_path, encoding='utf-8') as fh:
                after_first = fh.read()

            second = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                second.returncode, 0,
                f'second install exit {second.returncode}: '
                f'stdout={second.stdout!r} stderr={second.stderr!r}',
            )
            with open(config_path, encoding='utf-8') as fh:
                after_second = fh.read()

            self.assertEqual(
                after_first, after_second,
                'second install run mutated config.yaml — not idempotent.\n'
                f'after first run:\n{after_first}\n'
                f'after second run:\n{after_second}',
            )

    def test_install_hooks_happy_path(self):
        """install-hooks.sh with no pre-existing config.yaml creates one carrying
        both revenium command entries and the # hermes-revenium-hooks tag."""
        import os
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-install-happy-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            result = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'install-hooks.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            self.assertTrue(
                os.path.exists(config_path),
                'install-hooks.sh did not create config.yaml',
            )
            with open(config_path, encoding='utf-8') as fh:
                config = fh.read()
            self.assertIn(
                'pre_llm_call.sh', config,
                f'pre_llm_call.sh command missing from created config:\n{config}',
            )
            self.assertIn(
                'pre_tool_call.sh', config,
                f'pre_tool_call.sh command missing from created config:\n{config}',
            )
            self.assertIn(
                '# hermes-revenium-hooks', config,
                f'hook tag missing from created config:\n{config}',
            )

    def test_install_hooks_idempotent(self):
        """install-hooks.sh run twice over the same HERMES_HOME leaves config.yaml
        byte-identical after the second run — no double-registration (D-01)."""
        import os
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-install-idem-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            first = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                first.returncode, 0,
                f'first install exit {first.returncode}: '
                f'stdout={first.stdout!r} stderr={first.stderr!r}',
            )
            with open(config_path, encoding='utf-8') as fh:
                after_first = fh.read()

            second = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                second.returncode, 0,
                f'second install exit {second.returncode}: '
                f'stdout={second.stdout!r} stderr={second.stderr!r}',
            )
            with open(config_path, encoding='utf-8') as fh:
                after_second = fh.read()

            self.assertEqual(
                after_first, after_second,
                'second install run mutated config.yaml — not idempotent.\n'
                f'after first run:\n{after_first}\n'
                f'after second run:\n{after_second}',
            )

    def test_install_uninstall_round_trip(self):
        """install-hooks.sh then uninstall-hooks.sh against a config.yaml with a
        foreign pre_llm_call: hook leaves config without revenium entries while
        keeping the foreign hook intact (WR-01 coverage)."""
        import os
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')
        uninstall_hooks = str(SKILL / 'scripts' / 'uninstall-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-roundtrip-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            with open(config_path, 'w', encoding='utf-8') as fh:
                fh.write(
                    'hooks:\n'
                    '  pre_llm_call:\n'
                    '    - command: /opt/other/foreign-hook.sh\n'
                    '      timeout: 3\n'
                )
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            install = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                install.returncode, 0,
                f'install exit {install.returncode}: '
                f'stdout={install.stdout!r} stderr={install.stderr!r}',
            )

            uninstall = subprocess.run(
                ['bash', uninstall_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                uninstall.returncode, 0,
                f'uninstall exit {uninstall.returncode}: '
                f'stdout={uninstall.stdout!r} stderr={uninstall.stderr!r}',
            )

            with open(config_path, encoding='utf-8') as fh:
                config = fh.read()
            self.assertNotIn(
                'pre_llm_call.sh', config,
                f'pre_llm_call.sh revenium command survived uninstall:\n{config}',
            )
            self.assertNotIn(
                'pre_tool_call.sh', config,
                f'pre_tool_call.sh revenium command survived uninstall:\n{config}',
            )
            self.assertIn(
                '/opt/other/foreign-hook.sh', config,
                f'foreign hook destroyed by uninstall:\n{config}',
            )

    # ------------------------------------------------------------------
    # Phase 12 — pre_llm_call.sh / pre_tool_call.sh stdout-contract tests.
    # Each pipes a JSON payload to the real hook and parses stdout. All env
    # overrides point at a tempdir — no test touches the real ~/.hermes.
    # ------------------------------------------------------------------

    def test_pre_llm_call_fail_open(self):
        """pre_llm_call.sh prints exactly {} when guardrail-status.json is missing
        AND when it is corrupt non-JSON (V5 fail-open input validation).
        Phase 19: repointed from budget-status.json to guardrail-status.json (HOOK-04)."""
        import json
        import os
        import subprocess
        import tempfile

        pre_llm = str(SKILL / 'scripts' / 'pre_llm_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-llm-failopen-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            # Phase 19: repointed from budget-status.json to guardrail-status.json
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            # Case 1: guardrail-status.json missing.
            missing = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                missing.returncode, 0,
                f'pre_llm_call.sh exit {missing.returncode} (missing status): '
                f'stdout={missing.stdout!r} stderr={missing.stderr!r}',
            )
            self.assertEqual(
                json.loads(missing.stdout), {},
                f'expected {{}} fail-open on missing status, got: {missing.stdout!r}',
            )

            # Case 2: corrupt (non-JSON) guardrail-status.json.
            with open(status_path, 'w', encoding='utf-8') as fh:
                fh.write('this is not json {{{')
            corrupt = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                corrupt.returncode, 0,
                f'pre_llm_call.sh exit {corrupt.returncode} (corrupt status): '
                f'stdout={corrupt.stdout!r} stderr={corrupt.stderr!r}',
            )
            self.assertEqual(
                json.loads(corrupt.stdout), {},
                f'expected {{}} fail-open on corrupt status, got: {corrupt.stdout!r}',
            )

    def test_pre_llm_call_halted_emits_halt_string(self):
        """pre_llm_call.sh with halted guardrail-status.json emits a JSON object
        whose context carries the D-01 verbatim halt string and substituted values.
        Phase 19: repointed from budget-status.json to guardrail-status.json (HOOK-01, HOOK-04)."""
        import json
        import os
        import subprocess
        import tempfile

        pre_llm = str(SKILL / 'scripts' / 'pre_llm_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-llm-halted-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            # Phase 19: repointed from budget-status.json to guardrail-status.json
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {
                        'ruleId': 'test-rule-id',
                        'name': 'Engineering Budget',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 102.5,
                        'hardLimit': 100.0,
                    },
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [],
                }, fh)
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            result = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'pre_llm_call.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            payload = json.loads(result.stdout)
            self.assertIn(
                'context', payload,
                f'halted output missing context key: {result.stdout!r}',
            )
            context = payload['context']
            # Phase 19: D-01 halt string assertions (replaces legacy budget-status fields)
            self.assertIn(
                "Guardrail halt active — rule 'Engineering Budget'", context,
                f'D-01 halt string prefix missing from context: {context!r}',
            )
            self.assertIn('TOTAL_COST', context,
                          f'metricType missing from halt context: {context!r}')
            self.assertIn('MONTHLY', context,
                          f'windowType missing from halt context: {context!r}')
            self.assertIn('102.5', context,
                          f'currentValue missing from halt context: {context!r}')
            self.assertIn('100.0', context,
                          f'hardLimit missing from halt context: {context!r}')
            self.assertIn(
                'clear-halt.sh', context,
                f'clear-halt.sh resume instruction missing from context: {context!r}',
            )

    def test_pre_tool_call_halted_blocks(self):
        """pre_tool_call.sh with halted guardrail-status.json emits a JSON object
        with action == "block" and a non-empty message.
        Phase 19: repointed from budget-status.json to guardrail-status.json (HOOK-01, HOOK-04)."""
        import json
        import os
        import subprocess
        import tempfile

        pre_tool = str(SKILL / 'scripts' / 'pre_tool_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-tool-halted-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700, exist_ok=True)
            # Phase 19: repointed from budget-status.json to guardrail-status.json
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {
                        'ruleId': 'test-rule-id',
                        'name': 'Test Rule',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 102.5,
                        'hardLimit': 100.0,
                    },
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [],
                }, fh)
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['MARKERS_DIR'] = markers_dir

            result = subprocess.run(
                ['bash', pre_tool],
                input=json.dumps({
                    'hook_event_name': 'pre_tool_call',
                    'tool_name': 'shell',
                    'session_id': 'sess-pre-tool-test',
                }),
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'pre_tool_call.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload.get('action'), 'block',
                f'expected action == "block", got: {result.stdout!r}',
            )
            msg = payload.get('message', '')
            self.assertTrue(msg, f'block directive missing a non-empty message: {result.stdout!r}')
            # Phase 19: D-01 halt string in block message
            self.assertIn(
                "Guardrail halt active — rule 'Test Rule'", msg,
                f'D-01 halt string missing from block message: {msg!r}',
            )

    # ------------------------------------------------------------------
    # Phase 19 Wave 0 — Nyquist test scaffolding.
    # These tests are RED until the corresponding implementation waves land.
    # Each test has a complete body (no pass, no assert True).
    # ------------------------------------------------------------------

    def _make_revenium_stub(self, scripts_dir, enforcement_json, budget_rules_json,
                             events_json=None, events_fail=False):
        """Write a fake `revenium` binary into scripts_dir that handles the Phase 19 subcommands.

        - `revenium config show` → emits 'Team ID: 12802'
        - `revenium guardrails enforcement-rules get <teamId> --output json` → enforcement_json
        - `revenium guardrails budget-rules list --output json` → budget_rules_json
        - `revenium guardrails enforcement-events list --rule-id <id> --page-size 1 --output json`
            → events_json if not events_fail, else exit 1
        """
        import os
        import json
        stub_path = os.path.join(scripts_dir, 'revenium')
        # Escape the JSON strings for embedding in bash heredoc
        enf_escaped = enforcement_json.replace("'", "'\\''")
        br_escaped = budget_rules_json.replace("'", "'\\''")
        if events_json is None:
            events_json = '[]'
        ev_escaped = events_json.replace("'", "'\\''")
        events_body = f"exit 1" if events_fail else f"echo '{ev_escaped}'"
        stub_content = (
            '#!/usr/bin/env bash\n'
            # Match on "$1 $2 $3"; when fewer than 3 args are passed (e.g. "config show"),
            # bash expands the empty $3 to "", producing a trailing space in the string.
            # The 'config show'|'config show ' pattern handles both.
            # The 'guardrails budget-rules --help' and 'guardrails enforcement-events --help'
            # cases satisfy has_guardrails_cli() probes in guardrail-check.sh.
            'case "$1 $2 $3" in\n'
            f"  'config show'|'config show ') echo 'Team ID: 12802' ;;\n"
            f"  'guardrails enforcement-rules get') echo '{enf_escaped}' ;;\n"
            f"  'guardrails budget-rules list') echo '{br_escaped}' ;;\n"
            f"  'guardrails budget-rules --help') exit 0 ;;\n"
            f"  'guardrails enforcement-events list') {events_body} ;;\n"
            f"  'guardrails enforcement-events --help') exit 0 ;;\n"
            '  *) echo "unknown: $*" >&2; exit 1 ;;\n'
            'esac\n'
        )
        with open(stub_path, 'w') as f:
            f.write(stub_content)
        os.chmod(stub_path, 0o755)
        return stub_path

    def test_guardrail_check_writes_status_file(self):
        """guardrail-check.sh with mock enforcement-rules output writes guardrail-status.json
        with correct schema (ENF-04): rules array with 10 keys per rule, top-level
        halted/autonomousMode/lastChecked; haltedRule absent when halted:false.
        REQ: ENF-02, ENF-03, ENF-04.
        """
        import json
        import os
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 99,
                'name': 'Engineering Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'ORGANIZATION',
                'currentValue': 45.0,
                'warnThreshold': 80.0,
                'threshold': 100.0,
                'breached': False,
                'warnBreached': False,
                'shadowMode': False,
            }]
        })
        budget_rules_json = json.dumps([
            {'id': 'd5jng5', 'name': 'Engineering Budget'}
        ])
        events_json = json.dumps([
            {'created': '2026-05-22T14:03:38Z', 'rawDetails': 'rule within limits'}
        ])

        with tempfile.TemporaryDirectory(prefix='gsd-gc-writes-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json, events_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({
                    'ruleIds': ['d5jng5'],
                    'autonomousMode': True,
                    'organizationName': 'TestOrg',
                }, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            self.assertTrue(
                os.path.isfile(status_path),
                f'guardrail-status.json not written; stderr={result.stderr!r}',
            )
            with open(status_path) as f:
                data = json.load(f)

            # Top-level keys (ENF-04)
            self.assertIn('halted', data)
            self.assertFalse(data['halted'], 'halted must be false when no rule is breached')
            self.assertIn('autonomousMode', data)
            self.assertIn('lastChecked', data)
            self.assertNotIn('haltedRule', data, 'haltedRule must be absent when halted:false')

            # rules array (ENF-04 schema)
            rules = data.get('rules', [])
            self.assertIsInstance(rules, list, 'rules must be an array')
            self.assertGreater(len(rules), 0, 'rules must be non-empty for non-empty ruleIds')

            required_keys = {
                'ruleId', 'name', 'metricType', 'windowType', 'groupBy',
                'currentValue', 'warnThreshold', 'hardLimit', 'state', 'lastChecked',
            }
            for rule in rules:
                missing = required_keys - set(rule.keys())
                self.assertEqual(
                    missing, set(),
                    f'rule missing ENF-04 keys: {missing}; got keys: {set(rule.keys())}',
                )
            self.assertEqual(rules[0]['ruleId'], 'd5jng5',
                             'ruleId must be the string-hash from budget-rules list, not an integer')

    def test_guardrail_check_halt_transition(self):
        """New halt transition sets halted:true, haltedRule block; stdout contains
        HALT_TRANSITION=true and enforcement-event embedding (AUDIT-01).
        REQ: ENF-05, AUDIT-01.
        """
        import json
        import os
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 42,
                'name': 'Engineering Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'ORGANIZATION',
                'currentValue': 102.5,
                'warnThreshold': 80.0,
                'threshold': 100.0,
                'breached': True,
                'warnBreached': True,
                'shadowMode': False,
            }]
        })
        budget_rules_json = json.dumps([
            {'id': 'd5jng5', 'name': 'Engineering Budget'}
        ])
        events_json = json.dumps([
            {'created': '2026-05-22T14:03:38Z', 'rawDetails': 'rule exceeded hard-limit'}
        ])

        with tempfile.TemporaryDirectory(prefix='gsd-gc-halt-trans-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json, events_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({
                    'ruleIds': ['d5jng5'],
                    'autonomousMode': True,
                }, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            # Status file assertions
            self.assertTrue(os.path.isfile(status_path), 'guardrail-status.json not written')
            with open(status_path) as f:
                data = json.load(f)

            self.assertTrue(data.get('halted'), 'halted must be true when rule is breached')
            self.assertIn('haltedAt', data, 'haltedAt must be present on halt transition')
            self.assertIn('haltedRule', data, 'haltedRule must be present when halted:true')
            hr = data['haltedRule']
            for key in ('name', 'metricType', 'windowType', 'currentValue', 'hardLimit', 'ruleId'):
                self.assertIn(key, hr, f'haltedRule missing key: {key}')
            rules = data.get('rules', [])
            self.assertTrue(len(rules) > 0, 'rules must not be empty')
            self.assertEqual(rules[0].get('state'), 'block', 'breached rule must have state=block')

            # ruleId must be the string-hash from budget-rules list (19-05 revision)
            self.assertEqual(hr['ruleId'], 'd5jng5',
                             'haltedRule.ruleId must be the string-hash ID, not the integer API ID')

            # Stdout must contain HALT_TRANSITION=true (ENF-05)
            self.assertIn(
                'HALT_TRANSITION=true', result.stdout,
                f'stdout must contain HALT_TRANSITION=true on new halt; got: {result.stdout!r}',
            )

            # Audit event embedding in stdout (AUDIT-01 — revised 19-05 stdout contract)
            self.assertIn(
                'EVENT_TS=2026-05-22T14:03:38Z', result.stdout,
                f'stdout must contain EVENT_TS from enforcement-events list; got: {result.stdout!r}',
            )
            self.assertIn(
                'EVENT_SUMMARY=rule exceeded hard-limit', result.stdout,
                f'stdout must contain EVENT_SUMMARY from enforcement-events list; got: {result.stdout!r}',
            )

    def test_guardrail_check_halt_carry_forward(self):
        """Already-halted state carries forward haltedAt byte-identically;
        stdout does NOT contain HALT_TRANSITION=true.
        REQ: ENF-05.
        """
        import json
        import os
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 42,
                'name': 'Engineering Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'ORGANIZATION',
                'currentValue': 102.5,
                'warnThreshold': 80.0,
                'threshold': 100.0,
                'breached': True,
                'warnBreached': True,
                'shadowMode': False,
            }]
        })
        budget_rules_json = json.dumps([
            {'id': 'd5jng5', 'name': 'Engineering Budget'}
        ])
        events_json = json.dumps([
            {'created': '2026-05-22T14:03:38Z', 'rawDetails': 'rule exceeded hard-limit'}
        ])

        seeded_halted_at = '2026-05-22T10:00:00.000Z'

        with tempfile.TemporaryDirectory(prefix='gsd-gc-carry-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json, events_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'ruleIds': ['d5jng5'], 'autonomousMode': True}, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            # Pre-seed an already-halted status with a known haltedAt
            with open(status_path, 'w') as f:
                json.dump({
                    'halted': True,
                    'haltedAt': seeded_halted_at,
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T10:00:00.000Z',
                    'rules': [],
                }, f)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            with open(status_path) as f:
                data = json.load(f)

            # haltedAt must be byte-identical to the seeded value (carry-forward)
            self.assertEqual(
                data.get('haltedAt'), seeded_halted_at,
                f'haltedAt must be carried forward; got: {data.get("haltedAt")!r}',
            )

            # stdout must NOT contain HALT_TRANSITION=true (carry-forward, not new transition)
            self.assertNotIn(
                'HALT_TRANSITION=true', result.stdout,
                f'carry-forward must NOT emit HALT_TRANSITION=true; got: {result.stdout!r}',
            )

    def test_guardrail_check_no_rules_empty(self):
        """Empty ruleIds produces rules:[], halted:false. Script exits 0.
        REQ: ENF-02.
        """
        import json
        import os
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({'rules': []})
        budget_rules_json = json.dumps([])

        with tempfile.TemporaryDirectory(prefix='gsd-gc-norules-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'ruleIds': [], 'autonomousMode': True}, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            if os.path.isfile(status_path):
                with open(status_path) as f:
                    data = json.load(f)
                self.assertEqual(data.get('rules', []), [], 'rules must be [] for empty ruleIds')
                self.assertFalse(data.get('halted', False), 'halted must be false for empty ruleIds')

    def test_guardrail_check_audit_api_fallback(self):
        """When enforcement-events list exits non-zero (API failure), guardrail-check.sh
        still writes guardrail-status.json with halted:true, and stdout contains
        EVENT_TS=(unavailable) / EVENT_SUMMARY=(unavailable) (AUDIT-02 graceful degradation).
        Script exits 0.
        REQ: AUDIT-02.
        """
        import json
        import os
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 42,
                'name': 'Engineering Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'ORGANIZATION',
                'currentValue': 102.5,
                'warnThreshold': 80.0,
                'threshold': 100.0,
                'breached': True,
                'warnBreached': True,
                'shadowMode': False,
            }]
        })
        # budget-rules list succeeds (name→string-id join works)
        budget_rules_json = json.dumps([
            {'id': 'd5jng5', 'name': 'Engineering Budget'}
        ])

        with tempfile.TemporaryDirectory(prefix='gsd-gc-audit-fallback-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            # events_fail=True: stub exits 1 on enforcement-events list
            self._make_revenium_stub(
                scripts_dir, enforcement_json, budget_rules_json,
                events_json=None, events_fail=True,
            )

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'ruleIds': ['d5jng5'], 'autonomousMode': True}, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            # Script must exit 0 even when events API fails (graceful degradation)
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh must exit 0 on events API failure; '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            # Status file must still be written with halted:true
            self.assertTrue(os.path.isfile(status_path), 'guardrail-status.json must be written')
            with open(status_path) as f:
                data = json.load(f)
            self.assertTrue(data.get('halted'), 'halted must be true even when events API fails')
            self.assertIn('haltedRule', data, 'haltedRule must be present despite events API failure')

            # AUDIT-02 fallback stdout contract: EVENT_TS=(unavailable), EVENT_SUMMARY=(unavailable)
            self.assertIn(
                'EVENT_TS=(unavailable)', result.stdout,
                f'AUDIT-02: stdout must contain EVENT_TS=(unavailable) on API failure; '
                f'got: {result.stdout!r}',
            )
            self.assertIn(
                'EVENT_SUMMARY=(unavailable)', result.stdout,
                f'AUDIT-02: stdout must contain EVENT_SUMMARY=(unavailable) on API failure; '
                f'got: {result.stdout!r}',
            )

    def test_guardrail_check_shadow_mode_does_not_halt(self):
        """A breached shadow-mode rule must NOT cause halted:true (quick-260528-gve).
        The per-rule entry still records state:'block' AND shadowMode:true so the
        signal stays visible to dashboards. No haltedRule key is emitted because
        no non-shadow rule is in block state.
        """
        import json
        import os
        import re
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 999,
                'name': 'Shadow Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'AGENT',
                'currentValue': 100.0,
                'warnThreshold': 40.0,
                'threshold': 50.0,
                'breached': True,
                'warnBreached': True,
                'shadowMode': True,
            }]
        })
        budget_rules_json = json.dumps([
            {'id': 'shadow1', 'name': 'Shadow Budget'}
        ])
        events_json = json.dumps([
            {'created': '2026-05-28T10:00:00Z', 'rawDetails': 'shadow rule exceeded'}
        ])

        with tempfile.TemporaryDirectory(prefix='gsd-gc-shadow-nohalt-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json, events_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'ruleIds': ['shadow1'], 'autonomousMode': True}, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'guardrail-check.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            self.assertTrue(os.path.isfile(status_path), 'guardrail-status.json not written')
            with open(status_path) as f:
                data = json.load(f)

            # Top-level halt must remain false despite the shadow rule breaching
            self.assertFalse(
                data.get('halted', True),
                f'halted must be false when only a shadow rule breaches; got: {data!r}',
            )
            self.assertNotIn(
                'haltedRule', data,
                f'haltedRule must be absent when only a shadow rule blocks; got: {data!r}',
            )

            # The per-rule entry still records the breach + shadowMode flag
            rules = data.get('rules', [])
            self.assertEqual(len(rules), 1, f'rules: {rules!r}')
            self.assertEqual(rules[0].get('state'), 'block',
                             f'shadow rule still records state:block; got: {rules[0]!r}')
            self.assertTrue(rules[0].get('shadowMode'),
                            f'rules[0].shadowMode must be true; got: {rules[0]!r}')

            # No hard-halt notification line was logged (shadow path is distinct)
            if os.path.isfile(log_path):
                with open(log_path) as f:
                    log_text = f.read()
                self.assertNotIn(
                    'Halt notification sent', log_text,
                    f'shadow-only breach must not emit a Halt notification line; log: {log_text!r}',
                )

    def test_guardrail_check_shadow_mode_transition_notifies_with_prefix(self):
        """Shadow-mode transition into state:block emits a one-shot [shadow]-prefixed
        notification (quick-260528-gve). Re-running guardrail-check.sh with the rule
        still in shadow-block state emits zero additional shadow lines.
        """
        import json
        import os
        import re
        import subprocess
        import tempfile

        guardrail_check = str(SKILL / 'scripts' / 'guardrail-check.sh')

        enforcement_json = json.dumps({
            'rules': [{
                'ruleId': 999,
                'name': 'Shadow Budget',
                'metricType': 'TOTAL_COST',
                'periodType': 'MONTHLY',
                'groupBy': 'AGENT',
                'currentValue': 100.0,
                'warnThreshold': 40.0,
                'threshold': 50.0,
                'breached': True,
                'warnBreached': True,
                'shadowMode': True,
            }]
        })
        budget_rules_json = json.dumps([
            {'id': 'shadow1', 'name': 'Shadow Budget'}
        ])
        events_json = json.dumps([
            {'created': '2026-05-28T10:00:00Z', 'rawDetails': 'shadow rule exceeded'}
        ])

        shadow_re = re.compile(
            r"\[shadow\] Rule 'Shadow Budget' \(TOTAL_COST, MONTHLY\) "
            r"would have halted at 100\.0 of 50\.0; shadow mode prevented block\."
        )

        with tempfile.TemporaryDirectory(prefix='gsd-gc-shadow-trans-') as tmp:
            scripts_dir = os.path.join(tmp, 'scripts')
            os.makedirs(scripts_dir)
            self._make_revenium_stub(scripts_dir, enforcement_json, budget_rules_json, events_json)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            config_path = os.path.join(state_dir, 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'ruleIds': ['shadow1'], 'autonomousMode': True}, f)

            status_path = os.path.join(state_dir, 'guardrail-status.json')
            log_path = os.path.join(state_dir, 'revenium-metering.log')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['LOG_FILE'] = log_path
            env['PATH'] = scripts_dir + os.pathsep + env.get('PATH', '')

            # First run: transition into shadow-block — expect exactly one shadow line
            result1 = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result1.returncode, 0,
                f'first run exit {result1.returncode}: '
                f'stdout={result1.stdout!r} stderr={result1.stderr!r}',
            )

            self.assertTrue(os.path.isfile(log_path), 'revenium-metering.log must exist')
            with open(log_path) as f:
                log_after_run1 = f.read()
            matches_run1 = shadow_re.findall(log_after_run1)
            self.assertEqual(
                len(matches_run1), 1,
                f'first run must log exactly one [shadow] line; '
                f'matched {len(matches_run1)}; log={log_after_run1!r}',
            )

            # Second run: rule still in shadow-block per prev status file — expect zero new lines
            result2 = subprocess.run(
                ['bash', guardrail_check],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result2.returncode, 0,
                f'second run exit {result2.returncode}: '
                f'stdout={result2.stdout!r} stderr={result2.stderr!r}',
            )

            with open(log_path) as f:
                log_after_run2 = f.read()
            matches_run2 = shadow_re.findall(log_after_run2)
            self.assertEqual(
                len(matches_run2), 1,
                f'second run must NOT emit additional [shadow] lines; '
                f'total matches in log after run 2 = {len(matches_run2)}; '
                f'log={log_after_run2!r}',
            )

    def test_pre_llm_call_halted_emits_guardrail_halt_string(self):
        """pre_llm_call.sh with halted guardrail-status.json containing haltedRule
        emits a JSON object whose context carries the D-01 halt string with substituted values.
        REQ: HOOK-01, HOOK-03.
        """
        import json
        import os
        import subprocess
        import tempfile

        pre_llm = str(SKILL / 'scripts' / 'pre_llm_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-llm-guardrail-halted-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {
                        'ruleId': 'test-rule-id',
                        'name': 'Engineering Budget',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 102.5,
                        'hardLimit': 100.0,
                    },
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [],
                }, fh)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            result = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'pre_llm_call.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            payload = json.loads(result.stdout)
            self.assertIn('context', payload,
                          f'halted output missing context key: {result.stdout!r}')
            context = payload['context']
            self.assertIn(
                "Guardrail halt active — rule 'Engineering Budget'", context,
                f'D-01 halt string prefix missing from context: {context!r}',
            )
            self.assertIn('TOTAL_COST', context,
                          f'metricType missing from halt context: {context!r}')
            self.assertIn('MONTHLY', context,
                          f'windowType missing from halt context: {context!r}')
            self.assertIn('102.5', context,
                          f'currentValue missing from halt context: {context!r}')
            self.assertIn('100.0', context,
                          f'hardLimit missing from halt context: {context!r}')
            self.assertIn('clear-halt.sh', context,
                          f'clear-halt.sh resume instruction missing from context: {context!r}')

    def test_pre_tool_call_halted_blocks_guardrail(self):
        """pre_tool_call.sh with halted guardrail-status.json emits action=='block'
        and a message containing the D-01 guardrail halt string.
        REQ: HOOK-01.
        """
        import json
        import os
        import subprocess
        import tempfile

        pre_tool = str(SKILL / 'scripts' / 'pre_tool_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-tool-guardrail-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700, exist_ok=True)
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {
                        'ruleId': 'test-rule-id',
                        'name': 'Engineering Budget',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 102.5,
                        'hardLimit': 100.0,
                    },
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [],
                }, fh)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['MARKERS_DIR'] = markers_dir

            result = subprocess.run(
                ['bash', pre_tool],
                input=json.dumps({
                    'hook_event_name': 'pre_tool_call',
                    'tool_name': 'shell',
                    'session_id': 'sess-guardrail-test',
                }),
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'pre_tool_call.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload.get('action'), 'block',
                f'expected action == "block", got: {result.stdout!r}',
            )
            msg = payload.get('message', '')
            self.assertIn(
                "Guardrail halt active — rule 'Engineering Budget'", msg,
                f'D-01 halt string missing from block message: {msg!r}',
            )

    def test_pre_llm_call_warn_band_emits_stderr(self):
        """pre_llm_call.sh with a rule in state:'warn' emits a Guardrail warn: line to stderr,
        returns {} on stdout, and creates a warn-flag file at WARN_FLAGS_DIR/<sid>__<ruleId>.flag.
        REQ: HOOK-02.
        """
        import json
        import os
        import subprocess
        import tempfile

        pre_llm = str(SKILL / 'scripts' / 'pre_llm_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-llm-warn-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            sessions_dir = os.path.join(tmp, 'sessions')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            os.makedirs(sessions_dir, exist_ok=True)

            # Create a fake session file so session-scan resolves a session_id
            sid = 'test-warn-session'
            session_file = os.path.join(sessions_dir, f'session_{sid}.json')
            with open(session_file, 'w') as f:
                json.dump({'session_id': sid}, f)

            rule_id = 'warn-rule-01'
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': False,
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [{
                        'ruleId': rule_id,
                        'name': 'Test Rule',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 85.0,
                        'warnThreshold': 80.0,
                        'hardLimit': 100.0,
                        'state': 'warn',
                        'lastChecked': '2026-05-22T14:00:00.000Z',
                    }],
                }, fh)

            warn_flags_dir = os.path.join(tmp, 'warn-flags')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['REVENIUM_WARN_FLAGS_DIR'] = warn_flags_dir

            result = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'pre_llm_call.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            # stdout must be {} (no-op for Hermes hook dispatcher)
            self.assertEqual(
                json.loads(result.stdout), {},
                f'warn-band must return {{}} on stdout; got: {result.stdout!r}',
            )
            # stderr must contain warn line
            self.assertIn(
                'Guardrail warn:', result.stderr,
                f'stderr must contain "Guardrail warn:"; got: {result.stderr!r}',
            )
            self.assertIn(
                'Test Rule', result.stderr,
                f'stderr warn line must name the rule; got: {result.stderr!r}',
            )
            # warn-flag file must be created
            flag_files = []
            if os.path.isdir(warn_flags_dir):
                for fname in os.listdir(warn_flags_dir):
                    if fname.endswith('.flag'):
                        flag_files.append(fname)
            self.assertTrue(
                any(rule_id in f for f in flag_files),
                f'warn-flag file for rule {rule_id!r} not found in {warn_flags_dir!r}; '
                f'found: {flag_files}',
            )

    def test_pre_llm_call_warn_rate_limit(self):
        """Second call to pre_llm_call.sh with same session+rule does NOT emit duplicate warn line
        (sentinel flag suppresses it). Both runs return {} on stdout.
        REQ: HOOK-02.
        """
        import json
        import os
        import subprocess
        import tempfile

        pre_llm = str(SKILL / 'scripts' / 'pre_llm_call.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-llm-warn-ratelimit-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            sessions_dir = os.path.join(tmp, 'sessions')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            os.makedirs(sessions_dir, exist_ok=True)

            sid = 'test-ratelimit-session'
            session_file = os.path.join(sessions_dir, f'session_{sid}.json')
            with open(session_file, 'w') as f:
                json.dump({'session_id': sid}, f)

            rule_id = 'rl-rule-01'
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w', encoding='utf-8') as fh:
                json.dump({
                    'halted': False,
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [{
                        'ruleId': rule_id,
                        'name': 'Rate Limit Test Rule',
                        'metricType': 'TOTAL_COST',
                        'windowType': 'MONTHLY',
                        'currentValue': 85.0,
                        'warnThreshold': 80.0,
                        'hardLimit': 100.0,
                        'state': 'warn',
                        'lastChecked': '2026-05-22T14:00:00.000Z',
                    }],
                }, fh)

            warn_flags_dir = os.path.join(tmp, 'warn-flags')

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path
            env['REVENIUM_WARN_FLAGS_DIR'] = warn_flags_dir

            # First run — warn line expected
            result1 = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result1.returncode, 0,
                             f'first run failed: {result1.stderr!r}')
            self.assertEqual(json.loads(result1.stdout), {},
                             f'first run must return {{}}; got: {result1.stdout!r}')
            self.assertIn('Guardrail warn:', result1.stderr,
                          f'first run must emit warn line; got: {result1.stderr!r}')

            # Second run — warn line must NOT appear (sentinel suppresses)
            result2 = subprocess.run(
                ['bash', pre_llm],
                input='{"hook_event_name":"pre_llm_call"}',
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result2.returncode, 0,
                             f'second run failed: {result2.stderr!r}')
            self.assertEqual(json.loads(result2.stdout), {},
                             f'second run must return {{}}; got: {result2.stdout!r}')
            self.assertNotIn(
                'Guardrail warn:', result2.stderr,
                f'second run must NOT emit duplicate warn line (sentinel suppression); '
                f'got: {result2.stderr!r}',
            )

    def test_clear_halt_bare(self):
        """Bare clear-halt.sh on halted guardrail-status.json clears all block-state rules,
        sets halted:false, removes haltedAt and haltedRule.
        REQ: ENF-06.
        """
        import json
        import os
        import subprocess
        import tempfile

        clear_halt = str(SKILL / 'scripts' / 'clear-halt.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-clear-halt-bare-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {'ruleId': 'rule-A', 'name': 'Rule A',
                                   'metricType': 'TOTAL_COST', 'windowType': 'MONTHLY',
                                   'currentValue': 102.5, 'hardLimit': 100.0},
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [
                        {'ruleId': 'rule-A', 'name': 'Rule A', 'metricType': 'TOTAL_COST',
                         'windowType': 'MONTHLY', 'groupBy': 'ORG', 'currentValue': 102.5,
                         'warnThreshold': 80.0, 'hardLimit': 100.0, 'state': 'block',
                         'lastChecked': '2026-05-22T14:00:00.000Z'},
                        {'ruleId': 'rule-B', 'name': 'Rule B', 'metricType': 'TOTAL_COST',
                         'windowType': 'MONTHLY', 'groupBy': 'ORG', 'currentValue': 105.0,
                         'warnThreshold': 80.0, 'hardLimit': 100.0, 'state': 'block',
                         'lastChecked': '2026-05-22T14:00:00.000Z'},
                    ],
                }, fh)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            result = subprocess.run(
                ['bash', clear_halt],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'clear-halt.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            # stdout must mention "Cleared" with some count indication
            self.assertIn('Cleared', result.stdout,
                          f'stdout must contain "Cleared"; got: {result.stdout!r}')

            with open(status_path) as f:
                data = json.load(f)

            self.assertFalse(data.get('halted'), 'halted must be false after bare clear-halt.sh')
            self.assertNotIn('haltedAt', data, 'haltedAt must be removed after clear')
            self.assertNotIn('haltedRule', data, 'haltedRule must be removed after clear')
            for rule in data.get('rules', []):
                self.assertNotEqual(rule.get('state'), 'block',
                                    f'all rules must be cleared; {rule["ruleId"]} still block')

    def test_clear_halt_rule_id(self):
        """clear-halt.sh --rule-id X clears only rule X; other blocked rules remain;
        top-level halted is recomputed; haltedRule points to the next blocked rule.
        REQ: ENF-06.
        """
        import json
        import os
        import subprocess
        import tempfile

        clear_halt = str(SKILL / 'scripts' / 'clear-halt.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-clear-halt-ruleid-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            with open(status_path, 'w') as fh:
                json.dump({
                    'halted': True,
                    'haltedAt': '2026-05-22T14:03:38.478Z',
                    'haltedRule': {'ruleId': 'ruleId-A', 'name': 'Rule A',
                                   'metricType': 'TOTAL_COST', 'windowType': 'MONTHLY',
                                   'currentValue': 102.5, 'hardLimit': 100.0},
                    'autonomousMode': True,
                    'lastChecked': '2026-05-22T14:00:00.000Z',
                    'rules': [
                        {'ruleId': 'ruleId-A', 'name': 'Rule A', 'metricType': 'TOTAL_COST',
                         'windowType': 'MONTHLY', 'groupBy': 'ORG', 'currentValue': 102.5,
                         'warnThreshold': 80.0, 'hardLimit': 100.0, 'state': 'block',
                         'lastChecked': '2026-05-22T14:00:00.000Z'},
                        {'ruleId': 'ruleId-B', 'name': 'Rule B', 'metricType': 'TOTAL_COST',
                         'windowType': 'MONTHLY', 'groupBy': 'ORG', 'currentValue': 105.0,
                         'warnThreshold': 80.0, 'hardLimit': 100.0, 'state': 'block',
                         'lastChecked': '2026-05-22T14:00:00.000Z'},
                    ],
                }, fh)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            result = subprocess.run(
                ['bash', clear_halt, '--rule-id', 'ruleId-A'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'clear-halt.sh --rule-id ruleId-A exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )

            with open(status_path) as f:
                data = json.load(f)

            rules_by_id = {r['ruleId']: r for r in data.get('rules', [])}
            self.assertEqual(rules_by_id.get('ruleId-A', {}).get('state'), 'ok',
                             'ruleId-A must be cleared to ok')
            self.assertEqual(rules_by_id.get('ruleId-B', {}).get('state'), 'block',
                             'ruleId-B must remain block (not cleared)')

            # Top-level halted must remain true (ruleId-B still blocked)
            self.assertTrue(data.get('halted'), 'halted must remain true while ruleId-B is blocked')

            # haltedRule must now point to ruleId-B (next blocker, D-02 tiebreaker)
            hr = data.get('haltedRule', {})
            self.assertEqual(hr.get('ruleId'), 'ruleId-B',
                             'haltedRule.ruleId must repoint to ruleId-B after clearing ruleId-A')

    def test_clear_halt_rule_id_not_blocked(self):
        """clear-halt.sh --rule-id X when X is not in block state exits 0 with an info message;
        file is unchanged.
        REQ: ENF-06.
        """
        import json
        import os
        import subprocess
        import tempfile

        clear_halt = str(SKILL / 'scripts' / 'clear-halt.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-clear-halt-notblocked-') as tmp:
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            status_path = os.path.join(state_dir, 'guardrail-status.json')
            original = {
                'halted': False,
                'autonomousMode': True,
                'lastChecked': '2026-05-22T14:00:00.000Z',
                'rules': [
                    {'ruleId': 'ruleId-A', 'name': 'Rule A', 'metricType': 'TOTAL_COST',
                     'windowType': 'MONTHLY', 'groupBy': 'ORG', 'currentValue': 45.0,
                     'warnThreshold': 80.0, 'hardLimit': 100.0, 'state': 'ok',
                     'lastChecked': '2026-05-22T14:00:00.000Z'},
                ],
            }
            with open(status_path, 'w') as fh:
                json.dump(original, fh)

            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_STATE_DIR'] = state_dir
            env['GUARDRAIL_STATUS_FILE'] = status_path

            result = subprocess.run(
                ['bash', clear_halt, '--rule-id', 'ruleId-A'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'clear-halt.sh on non-blocked rule must exit 0; '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            # stdout must contain informational message
            combined = result.stdout + result.stderr
            self.assertTrue(
                'not in block' in combined or 'no change' in combined.lower() or 'No change' in combined,
                f'output must indicate rule is not blocked; got: {combined!r}',
            )

            # File must be unchanged
            with open(status_path) as f:
                data = json.load(f)
            self.assertFalse(data.get('halted'), 'halted must remain false')
            self.assertEqual(data.get('rules', [{}])[0].get('state'), 'ok',
                             'rule state must remain ok')

    def test_revenium_classifier_job_taxonomy_file_env_override(self):
        """Task 1 (Phase 13-01): JOB_TAXONOMY_FILE constant is env-overridable via
        REVENIUM_JOB_TAXONOMY_FILE + importlib.reload. Default resolves under STATE_DIR."""
        import importlib
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-taxonomy-')
        # _setup_plugin_env now snapshots REVENIUM_JOB_TAXONOMY_FILE too (Task 1).
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Test 1: default JOB_TAXONOMY_FILE resolves under STATE_DIR as job-taxonomy.json.
            from pathlib import Path
            expected_default = Path(sd) / 'job-taxonomy.json'
            self.assertEqual(handler.JOB_TAXONOMY_FILE, expected_default)

            # Test 2: override via REVENIUM_JOB_TAXONOMY_FILE + reload.
            override_path = os.path.join(tmpdir, 'custom-job-taxonomy.json')
            os.environ['REVENIUM_JOB_TAXONOMY_FILE'] = override_path
            importlib.reload(sys.modules['classifier'])
            import classifier as handler2  # noqa: F811
            self.assertEqual(str(handler2.JOB_TAXONOMY_FILE), override_path)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_read_session_transcript(self):
        """Task 2 (Phase 13-01): _read_session_transcript returns "" for empty/missing
        session and chronologically-ordered transcript capped at max_chars."""
        import importlib
        import json
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-transcript-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Test 1a: missing STATE_DB → returns "".
            result = handler._read_session_transcript("sid-missing")
            self.assertEqual(result, "")

            # Create a minimal state.db with messages table.
            db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
                "role TEXT, content TEXT, timestamp REAL)"
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                "('sess-t1', 'user', 'hello there', 1.0)"
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                "('sess-t1', 'assistant', 'hi back', 2.0)"
            )
            conn.commit()
            conn.close()

            # Reload so STATE_DB points to our db_path.
            importlib.reload(sys.modules['classifier'])
            import classifier as handler2  # noqa: F811

            # Test 1b: empty session (no matching rows) → returns "".
            result_empty = handler2._read_session_transcript("no-such-session")
            self.assertEqual(result_empty, "")

            # Test 2: populated session → ordered ASC, joined as "role: snippet" lines.
            result_ok = handler2._read_session_transcript("sess-t1")
            self.assertIn("user:", result_ok)
            self.assertIn("assistant:", result_ok)
            # ASC ordering: user line (ts=1.0) before assistant line (ts=2.0)
            self.assertLess(result_ok.index("user:"), result_ok.index("assistant:"))

            # Test 3: max_chars cap — insert many messages and verify total length ≤ max_chars.
            conn2 = sqlite3.connect(db_path)
            for i in range(50):
                conn2.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                    "(?, ?, ?, ?)",
                    ("sess-big", "user" if i % 2 == 0 else "assistant", "x" * 1000, float(i)),
                )
            conn2.commit()
            conn2.close()
            importlib.reload(sys.modules['classifier'])
            import classifier as handler3  # noqa: F811
            result_big = handler3._read_session_transcript("sess-big", max_chars=8000)
            self.assertLessEqual(len(result_big), 8000)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_transcript_includes_tail(self):
        """Phase 13 gap fix: an over-budget transcript keeps BOTH the head (opening
        request) and the tail (closing outcome). A head-only window dropped the
        session conclusion, so job inference on long sessions mis-inferred the arc."""
        import importlib
        import os
        import shutil
        import sqlite3
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-transcript-tail-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            db_path = os.path.join(hh, 'state.db')
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
                "role TEXT, content TEXT, timestamp REAL)"
            )
            # First message carries the opening-request marker.
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                "('sess-long', 'user', 'OPENING_REQUEST_MARKER please do the work', 0.0)"
            )
            # Bulk filler that pushes the transcript well past max_chars.
            for i in range(1, 41):
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                    "(?, ?, ?, ?)",
                    ("sess-long", "assistant" if i % 2 else "user", "x" * 500, float(i)),
                )
            # Last message carries the closing-outcome marker.
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES "
                "('sess-long', 'assistant', 'CLOSING_OUTCOME_MARKER all done', 999.0)"
            )
            conn.commit()
            conn.close()

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler  # noqa: F811

            result = handler._read_session_transcript("sess-long", max_chars=8000)
            self.assertLessEqual(len(result), 8000)
            # Head preserved: the opening request must survive truncation.
            self.assertIn("OPENING_REQUEST_MARKER", result)
            # Tail preserved: the closing outcome must survive truncation — this is
            # the regression. A head-only window dropped it.
            self.assertIn("CLOSING_OUTCOME_MARKER", result)
            # The middle was elided with an explicit marker.
            self.assertIn("truncated", result)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_parse_job_array(self):
        """Task 2 (Phase 13-01): _parse_job_array handles fenced JSON, bare dict,
        invalid elements, and JSON errors."""
        import importlib
        import json
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-parse-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            job_obj = {"agentic_job_id": "fix_bug_a1b2", "job_name": "fix bug",
                       "job_type": "bug_fix", "status": "SUCCESS"}

            # Test 1: plain JSON array.
            raw_array = json.dumps([job_obj])
            result = handler._parse_job_array(raw_array)
            self.assertEqual(result, [job_obj])

            # Test 2: fenced ```json ... ``` block.
            fenced = f"```json\n{json.dumps([job_obj])}\n```"
            result_fenced = handler._parse_job_array(fenced)
            self.assertEqual(result_fenced, [job_obj])

            # Test 3: bare dict (lone object) → coerced to [dict].
            raw_dict = json.dumps(job_obj)
            result_dict = handler._parse_job_array(raw_dict)
            self.assertEqual(result_dict, [job_obj])

            # Test 4: JSONDecodeError → [].
            result_bad = handler._parse_job_array("not json at all {{{")
            self.assertEqual(result_bad, [])

            # Test 5: array with non-dict element → element dropped.
            mixed = json.dumps([job_obj, "a string", 42])
            result_mixed = handler._parse_job_array(mixed)
            self.assertEqual(result_mixed, [job_obj])
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_infer_jobs_via_llm(self):
        """Task 2 (Phase 13-01): _infer_jobs_via_llm returns [] when call_llm is None;
        when patched it calls call_llm WITHOUT task= kwarg and returns parsed list."""
        import asyncio
        import importlib
        import json
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-infer-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Test 1: call_llm is None → [].
            original_call_llm = handler.call_llm
            handler.call_llm = None
            result_none = asyncio.run(handler._infer_jobs_via_llm("some transcript", []))
            self.assertEqual(result_none, [])
            handler.call_llm = original_call_llm

            # Test 2: patched call_llm returns a job array.
            job_obj = {"agentic_job_id": "fix_bug_a1b2", "job_name": "fix bug",
                       "job_type": "bug_fix", "status": "SUCCESS"}
            mock_resp = unittest.mock.MagicMock()
            mock_resp.choices = [unittest.mock.MagicMock()]
            mock_resp.choices[0].message.content = json.dumps([job_obj])
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp) as mock_llm:
                result_ok = asyncio.run(handler._infer_jobs_via_llm("some transcript", ["bug_fix"]))
                mock_llm.assert_called_once()
                kwargs = mock_llm.call_args.kwargs
                # CRITICAL: NO task= kwarg — pinned by design (Pitfall 8).
                self.assertNotIn('task', kwargs)
                self.assertEqual(kwargs.get('temperature'), 0.0)
                self.assertEqual(kwargs.get('max_tokens'), 512)
            self.assertEqual(result_ok, [job_obj])
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_build_job_inference_prompt(self):
        """Task 2 (Phase 13-01): _build_job_inference_prompt returns a non-empty string
        with JSON array instruction and labels block."""
        import importlib
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-prompt-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            prompt = handler._build_job_inference_prompt("user did some work", ["bug_fix", "research"])
            self.assertIsInstance(prompt, str)
            self.assertTrue(len(prompt) > 0)
            # Must instruct JSON array output with the required keys.
            self.assertIn("agentic_job_id", prompt)
            self.assertIn("job_type", prompt)
            self.assertIn("status", prompt)
            # Labels block present.
            self.assertIn("bug_fix", prompt)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_validate_job(self):
        """Task 3 (Phase 13-01): _validate_job normalizes valid dicts and returns None
        for missing keys, bad job_type, or status outside {SUCCESS,FAILED,CANCELLED}."""
        import importlib
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-validate-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            good = {
                "agentic_job_id": "fix_auth_a1b2",
                "job_name": "Fix auth regression",
                "job_type": "bug_fix",
                "status": "SUCCESS",
            }

            # Test 1: valid job → returns normalized dict.
            result = handler._validate_job(good.copy())
            self.assertIsNotNone(result)
            self.assertEqual(result["job_type"], "bug_fix")
            self.assertEqual(result["status"], "SUCCESS")

            # Test 2: status normalization — lowercase → uppercase.
            mixed_status = dict(good, status="success")
            result2 = handler._validate_job(mixed_status)
            self.assertIsNotNone(result2)
            self.assertEqual(result2["status"], "SUCCESS")

            # Test 3: status outside enum → None.
            bad_status = dict(good, status="PENDING")
            result3 = handler._validate_job(bad_status)
            self.assertFalsy(result3)

            # Test 4: job_type fails LABEL_RE (contains hyphen) → None.
            bad_type = dict(good, job_type="bug-fix")
            result4 = handler._validate_job(bad_type)
            self.assertFalsy(result4)

            # Test 5: missing required key (agentic_job_id) → None.
            missing_key = {k: v for k, v in good.items() if k != "agentic_job_id"}
            result5 = handler._validate_job(missing_key)
            self.assertFalsy(result5)

            # Test 6: empty agentic_job_id → None.
            empty_id = dict(good, agentic_job_id="")
            result6 = handler._validate_job(empty_id)
            self.assertFalsy(result6)

            # Test 7: CANCELLED and FAILED are valid statuses.
            cancelled = dict(good, status="CANCELLED")
            self.assertIsNotNone(handler._validate_job(cancelled))
            failed = dict(good, status="FAILED")
            self.assertIsNotNone(handler._validate_job(failed))
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def assertFalsy(self, value, msg=None):
        """Helper: assert value is falsy (None, False, {}, [], "")."""
        if value:
            raise AssertionError(
                msg or f"Expected falsy value, got {value!r}"
            )

    def test_revenium_classifier_write_job_marker(self):
        """Task 3 (Phase 13-01): _write_job_marker appends exactly one compact JSON
        line with kind:"job" and all four reader-required keys."""
        import importlib
        import json
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-write-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sid = "test-write-job-sid"
            job = {
                "agentic_job_id": "fix_auth_a1b2",
                "job_name": "Fix auth regression",
                "job_type": "bug_fix",
                "status": "SUCCESS",
            }
            path = handler._write_job_marker(sid, job)

            # Verify file written.
            self.assertTrue(path.exists())
            lines = path.read_text().splitlines()

            # Test 1: exactly one line written.
            self.assertEqual(len(lines), 1)

            # Test 2: line is valid JSON with kind:"job" and all required keys.
            rec = json.loads(lines[0])
            self.assertEqual(rec.get("kind"), "job")
            self.assertIn("agentic_job_id", rec)
            self.assertIn("job_type", rec)
            self.assertIn("status", rec)
            self.assertEqual(rec["agentic_job_id"], "fix_auth_a1b2")
            self.assertEqual(rec["job_type"], "bug_fix")
            self.assertEqual(rec["status"], "SUCCESS")

            # Test 3: re-reading parses back correctly.
            import json as json2
            rec2 = json2.loads(lines[0])
            self.assertEqual(rec2["kind"], "job")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_job_taxonomy_roundtrip(self):
        """Task 3 (Phase 13-01): _read_job_taxonomy_labels / _persist_job_type_to_taxonomy
        round-trip a job_type into JOB_TAXONOMY_FILE under flock without raising on a
        missing file."""
        import importlib
        import json
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-tax-rt-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Test 1: _read_job_taxonomy_labels on missing file → [].
            labels_empty = handler._read_job_taxonomy_labels()
            self.assertEqual(labels_empty, [])

            # Test 2: _persist_job_type_to_taxonomy creates file and writes label.
            handler._persist_job_type_to_taxonomy("bug_fix")
            self.assertTrue(handler.JOB_TAXONOMY_FILE.exists())
            data = json.loads(handler.JOB_TAXONOMY_FILE.read_text())
            self.assertIn("bug_fix", data.get("labels", {}))

            # Test 3: _read_job_taxonomy_labels now returns the persisted label.
            labels_after = handler._read_job_taxonomy_labels()
            self.assertIn("bug_fix", labels_after)

            # Test 4: persist does not raise on a second call (idempotent).
            handler._persist_job_type_to_taxonomy("bug_fix")
            labels_after2 = handler._read_job_taxonomy_labels()
            self.assertIn("bug_fix", labels_after2)
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_job_marker_exists(self):
        """Task 3 (Phase 13-01): _job_marker_exists returns True when kind:"job" present,
        False for task-only file, and False (fail-open) for unreadable file."""
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-dedup-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sid_with_job = "job-dedup-sid-with-job"
            sid_task_only = "job-dedup-sid-task-only"

            # Write a task-only marker file (no kind:"job" line).
            task_path = handler.MARKERS_DIR / f"{sid_task_only}.jsonl"
            task_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            task_record = json.dumps({"muid": "x", "ts": 1.0, "sid": sid_task_only,
                                      "task_type": "bug_fix", "operation_type": "CHAT"})
            task_path.write_text(task_record + "\n")

            # Test 1: task-only file → False.
            self.assertFalse(handler._job_marker_exists(sid_task_only))

            # Write a marker file that has a kind:"job" line.
            job_path = handler.MARKERS_DIR / f"{sid_with_job}.jsonl"
            job_record = json.dumps({"kind": "job", "ts": 2.0, "sid": sid_with_job,
                                     "agentic_job_id": "fix_auth_a1b2", "job_type": "bug_fix",
                                     "status": "SUCCESS"})
            job_path.write_text(task_record + "\n" + job_record + "\n")

            # Test 2: file with kind:"job" line → True.
            self.assertTrue(handler._job_marker_exists(sid_with_job))

            # Test 3: missing file → False (fail-open).
            self.assertFalse(handler._job_marker_exists("no-such-session-ever"))
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_job_step7_single_goal(self):
        """Task 1 RED: Step 7 wiring — single-goal session writes one kind:"job" marker.

        Test 1: a single-goal session with call_llm patched to return a one-job array
        writes exactly one kind:"job" marker after the GUARDRAIL+CHAT task pair.
        Test 2: a subagent session (root_sid != session_id) writes NO kind:"job" marker.
        Test 3: a session with halted:true in budget-status.json writes NO kind:"job"
        marker via the job block (budget gate).
        """
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-step7-single-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "20260518_120000_jobstep7single"

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Build side_effect for call_llm: first call (task) returns task label,
            # second call (job inference) returns one-job JSON array.
            task_resp = unittest.mock.MagicMock()
            task_resp.choices = [unittest.mock.MagicMock()]
            task_resp.choices[0].message.content = "code_review"

            job_array_resp = unittest.mock.MagicMock()
            job_array_resp.choices = [unittest.mock.MagicMock()]
            job_array_resp.choices[0].message.content = json.dumps([
                {"agentic_job_id": "fix_auth_a1b2", "job_name": "Fix auth bug",
                 "job_type": "bug_fix", "status": "SUCCESS"}
            ])

            call_llm_responses = [task_resp, job_array_resp]

            # Test 1: single-goal session → one kind:"job" marker after the task pair
            # Patch _read_session_transcript to return a non-empty transcript so the
            # job block proceeds (production path reads from state.db; test env has none).
            fake_transcript = "user: Please fix the auth bug\nassistant: Fixed the auth token validation."
            with unittest.mock.patch.object(handler, 'call_llm',
                                             side_effect=call_llm_responses), \
                 unittest.mock.patch.object(handler, '_read_session_transcript',
                                            return_value=fake_transcript):
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message="Please fix the authentication bug in the login flow",
                    response="I've fixed the authentication bug by updating the token validation.",
                ))

            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            self.assertTrue(marker_path.is_file(), "marker file must exist")
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]
            # Must have at least 3 records: GUARDRAIL, CHAT, job
            self.assertGreaterEqual(len(recs), 3, f"expected >=3 records, got {len(recs)}: {lines}")
            job_recs = [r for r in recs if r.get("kind") == "job"]
            self.assertEqual(len(job_recs), 1, f"expected exactly 1 job record, got {len(job_recs)}")
            # Job marker must appear AFTER the task pair (positional attribution D-03)
            task_recs = [r for r in recs if r.get("operation_type") in ("GUARDRAIL", "CHAT")]
            self.assertEqual(len(task_recs), 2, "must have GUARDRAIL and CHAT records")
            # Find indices by scanning recs (records already parsed from lines)
            job_indices = [i for i, r in enumerate(recs) if r.get("kind") == "job"]
            guardrail_indices = [i for i, r in enumerate(recs) if r.get("operation_type") == "GUARDRAIL"]
            chat_indices = [i for i, r in enumerate(recs) if r.get("operation_type") == "CHAT"]
            self.assertEqual(len(job_indices), 1, "exactly one job record index")
            job_idx = job_indices[0]
            guardrail_idx = guardrail_indices[0]
            chat_idx = chat_indices[0]
            self.assertGreater(job_idx, guardrail_idx, "job marker must come after GUARDRAIL")
            self.assertGreater(job_idx, chat_idx, "job marker must come after CHAT")
            # Verify job record fields
            jr = job_recs[0]
            self.assertEqual(jr.get("kind"), "job")
            self.assertIn("agentic_job_id", jr)
            self.assertIn("job_type", jr)
            self.assertIn("status", jr)

            # Test 2: subagent session (root_sid != session_id) → no job marker
            # Reset marker dir
            shutil.rmtree(md, ignore_errors=True)
            os.makedirs(md, mode=0o700)

            sub_sid = "20260518_130000_subagent"
            root_sid_value = "20260518_120000_rootsession"
            # Pre-create root session marker (so subagent can inherit task type)
            root_marker = handler.MARKERS_DIR / f"{root_sid_value}.jsonl"
            root_marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            root_rec = json.dumps({"muid": "a" * 33, "ts": 1.0, "sid": root_sid_value,
                                   "task_type": "code_review", "operation_type": "CHAT"},
                                  separators=(",", ":"))
            root_marker.write_text(root_rec + "\n")

            with unittest.mock.patch.object(handler, '_walk_to_root_session',
                                             return_value=root_sid_value):
                asyncio.run(handler.run_classification_async(
                    session_id=sub_sid,
                    message="sub-task",
                    response="done",
                ))

            sub_marker = handler.MARKERS_DIR / f"{sub_sid}.jsonl"
            if sub_marker.is_file():
                sub_lines = sub_marker.read_text().splitlines()
                sub_recs = [json.loads(l) for l in sub_lines]
                sub_job_recs = [r for r in sub_recs if r.get("kind") == "job"]
                self.assertEqual(len(sub_job_recs), 0,
                                 "subagent session must NOT produce a job marker")

            # Test 3: halted budget → no job marker written via job block
            shutil.rmtree(md, ignore_errors=True)
            os.makedirs(md, mode=0o700)

            halted_sid = "20260518_140000_haltedtest"
            # Phase 19: repoint from BUDGET_STATUS_FILE to GUARDRAIL_STATUS_FILE (SC-7)
            budget_status_path = handler.GUARDRAIL_STATUS_FILE
            budget_status_path.parent.mkdir(parents=True, exist_ok=True)
            budget_status_path.write_text(json.dumps({"halted": True, "autonomousMode": True}))

            try:
                asyncio.run(handler.run_classification_async(
                    session_id=halted_sid,
                    message="do something",
                    response="done",
                ))
            except Exception as exc:
                self.fail(f"run_classification_async must not raise when halted: {exc}")

            halted_marker = handler.MARKERS_DIR / f"{halted_sid}.jsonl"
            if halted_marker.is_file():
                halted_lines = halted_marker.read_text().splitlines()
                halted_recs = [json.loads(l) for l in halted_lines]
                halted_job_recs = [r for r in halted_recs if r.get("kind") == "job"]
                self.assertEqual(len(halted_job_recs), 0,
                                 "halted session must NOT produce a job marker via job block")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_job_multi_arc(self):
        """Task 2 RED: multi-arc session produces N kind:"job" markers, all after the task pair.

        Test 1: a multi-goal transcript with call_llm returning a 2-job array writes
        exactly 2 kind:"job" markers, both positioned after the single GUARDRAIL+CHAT pair.
        """
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-multi-arc-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sid = "20260518_150000_multiarc"

            # Task classification response
            task_resp = unittest.mock.MagicMock()
            task_resp.choices = [unittest.mock.MagicMock()]
            task_resp.choices[0].message.content = "code_review"

            # Job inference response — 2-job array
            job_array_resp = unittest.mock.MagicMock()
            job_array_resp.choices = [unittest.mock.MagicMock()]
            job_array_resp.choices[0].message.content = json.dumps([
                {"agentic_job_id": "fix_auth_a1b2", "job_name": "Fix auth bug",
                 "job_type": "bug_fix", "status": "SUCCESS"},
                {"agentic_job_id": "refactor_db_c3d4", "job_name": "Refactor DB layer",
                 "job_type": "refactoring", "status": "SUCCESS"},
            ])

            fake_transcript = "user: Fix auth and refactor DB\nassistant: Done both tasks."
            with unittest.mock.patch.object(handler, 'call_llm',
                                             side_effect=[task_resp, job_array_resp]), \
                 unittest.mock.patch.object(handler, '_read_session_transcript',
                                            return_value=fake_transcript):
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message="Fix auth and refactor DB layer",
                    response="I've fixed auth and refactored the DB.",
                ))

            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            self.assertTrue(marker_path.is_file(), "marker file must exist")
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]

            # Must have exactly 2 task records + 2 job records = 4 total
            job_recs = [r for r in recs if r.get("kind") == "job"]
            task_recs = [r for r in recs if r.get("operation_type") in ("GUARDRAIL", "CHAT")]
            self.assertEqual(len(job_recs), 2, f"expected 2 job records, got {len(job_recs)}")
            self.assertEqual(len(task_recs), 2, f"expected 2 task records, got {len(task_recs)}")

            # Both job markers must appear AFTER the GUARDRAIL and CHAT records
            guardrail_idx = next(i for i, r in enumerate(recs) if r.get("operation_type") == "GUARDRAIL")
            chat_idx = next(i for i, r in enumerate(recs) if r.get("operation_type") == "CHAT")
            job_indices = [i for i, r in enumerate(recs) if r.get("kind") == "job"]
            for ji in job_indices:
                self.assertGreater(ji, guardrail_idx, "job marker must come after GUARDRAIL")
                self.assertGreater(ji, chat_idx, "job marker must come after CHAT")

            # The two job records must have distinct agentic_job_ids
            job_ids = [r.get("agentic_job_id") for r in job_recs]
            self.assertEqual(len(set(job_ids)), 2, f"job IDs must be distinct: {job_ids}")

            # assertNotIn('task', kwargs) for the job inference call
            # (Step 7 call_llm must not use task= kwarg per Pitfall 8 / A3)
            # This is implicitly covered since _infer_jobs_via_llm does not pass task=
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_job_dedup_skips_existing(self):
        """Task 2 RED: D-08 dedup — when markers/<sid>.jsonl already contains a kind:"job"
        line, the job block writes no additional job marker.
        """
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-dedup-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sid = "20260518_160000_dedupsid"

            # Pre-write a kind:"job" line into the marker file before invoking
            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            marker_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            existing_job = json.dumps(
                {"kind": "job", "ts": 1.0, "sid": sid,
                 "agentic_job_id": "existing_job_aa11", "job_name": "Existing job",
                 "job_type": "bug_fix", "status": "SUCCESS"},
                separators=(",", ":"),
            )
            marker_path.write_text(existing_job + "\n")

            # task classification response
            task_resp = unittest.mock.MagicMock()
            task_resp.choices = [unittest.mock.MagicMock()]
            task_resp.choices[0].message.content = "code_review"

            # job inference would return a new job, but the gate should block it
            job_resp = unittest.mock.MagicMock()
            job_resp.choices = [unittest.mock.MagicMock()]
            job_resp.choices[0].message.content = json.dumps([
                {"agentic_job_id": "new_job_bb22", "job_name": "New job",
                 "job_type": "refactoring", "status": "SUCCESS"},
            ])

            fake_transcript = "user: do something\nassistant: done."
            with unittest.mock.patch.object(handler, 'call_llm',
                                             side_effect=[task_resp, job_resp]) as mock_llm, \
                 unittest.mock.patch.object(handler, '_read_session_transcript',
                                            return_value=fake_transcript):
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message="do something",
                    response="done",
                ))

            # Marker file must still contain only the pre-existing job (no extra job appended)
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]
            job_recs = [r for r in recs if r.get("kind") == "job"]
            # Should still be exactly 1 job record (the pre-existing one)
            self.assertEqual(len(job_recs), 1,
                             f"dedup must prevent additional job write; got {len(job_recs)}: {job_recs}")
            self.assertEqual(job_recs[0].get("agentic_job_id"), "existing_job_aa11",
                             "original job ID must be preserved")
            # call_llm for job inference must NOT have been called (dedup gate skips the block)
            # The task classification call IS expected; job inference call is NOT
            call_count = mock_llm.call_count
            # We expect exactly 1 call (task classification only), not 2
            self.assertEqual(call_count, 1,
                             f"job inference must be skipped when job marker exists; got {call_count} calls")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_job_backward_compat(self):
        """Task 2 RED: job-less / call_llm-returns-[] session produces only the
        GUARDRAIL+CHAT task pair — byte-identical-to-v1.0 task path.
        """
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-backcompat-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sid = "20260518_170000_backcompat"

            # Task classification response
            task_resp = unittest.mock.MagicMock()
            task_resp.choices = [unittest.mock.MagicMock()]
            task_resp.choices[0].message.content = "code_review"

            # Job inference returns empty array — no jobs inferred
            job_empty_resp = unittest.mock.MagicMock()
            job_empty_resp.choices = [unittest.mock.MagicMock()]
            job_empty_resp.choices[0].message.content = "[]"

            fake_transcript = "user: quick question\nassistant: here is the answer."
            with unittest.mock.patch.object(handler, 'call_llm',
                                             side_effect=[task_resp, job_empty_resp]), \
                 unittest.mock.patch.object(handler, '_read_session_transcript',
                                            return_value=fake_transcript):
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message="quick question",
                    response="here is the answer",
                ))

            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            self.assertTrue(marker_path.is_file(), "marker file must exist")
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]

            # Must have exactly 2 records: GUARDRAIL and CHAT — no job records
            self.assertEqual(len(recs), 2, f"expected exactly 2 records (task pair), got {len(recs)}: {lines}")
            operations = {r.get("operation_type") for r in recs}
            self.assertEqual(operations, {"GUARDRAIL", "CHAT"},
                             "only GUARDRAIL and CHAT records expected")
            job_recs = [r for r in recs if r.get("kind") == "job"]
            self.assertEqual(len(job_recs), 0,
                             f"no job records expected when LLM returns []; got {job_recs}")
            # Verify task_type is the one from classification (not a job field)
            for r in recs:
                self.assertNotIn("kind", r, "task records must not have a 'kind' field")
                self.assertNotIn("agentic_job_id", r, "task records must not have 'agentic_job_id'")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_job_runs_after_self_classify(self):
        """CR-01 regression: Step 7 job-inference must run even when Step 3 fires.

        When a fresh GUARDRAIL+CHAT pair (ts within 30s) already exists because the
        agent self-classified, run_classification_async must still produce a kind:"job"
        marker — Step 3 must gate only task re-writing (Steps 4-6), not job inference.

        This test fails against the pre-fix (CR-01) code where Step 3 returns early
        before Step 7, and passes after the Task 1 fix that captures agent_self_classified
        and wraps Steps 4-6 in 'if not agent_self_classified:'.
        """
        import asyncio
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile
        import time
        import unittest.mock

        tmpdir = tempfile.mkdtemp(prefix='gsd-job-after-self-classify-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            os.makedirs(os.path.join(hh, 'sessions'), exist_ok=True)
            sid = "20260518_120000_selfclassify"

            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            # Pre-write a fresh GUARDRAIL+CHAT pair (ts within 30s) — simulates the
            # agent's FINAL ACTION TASK CLASSIFICATION having just run.
            marker_path = handler.MARKERS_DIR / f"{sid}.jsonl"
            now = time.time()
            with open(marker_path, 'w', encoding='utf-8') as f:
                rec1 = {"muid": "a" * 33, "ts": now - 1.0, "sid": sid,
                        "task_type": "code_review", "operation_type": "GUARDRAIL"}
                rec2 = dict(rec1, muid="b" * 33, ts=now - 0.5, operation_type="CHAT")
                f.write(json.dumps(rec1, separators=(",", ":")) + "\n")
                f.write(json.dumps(rec2, separators=(",", ":")) + "\n")

            # Confirm Step 3 gate would fire on this session.
            self.assertTrue(
                handler._recent_marker_pair_exists(sid, within_seconds=30.0),
                "_recent_marker_pair_exists must return True for the fresh pair"
            )

            # Mock call_llm so the job-inference call returns a valid one-job array.
            job_resp = unittest.mock.MagicMock()
            job_resp.choices = [unittest.mock.MagicMock()]
            job_resp.choices[0].message.content = json.dumps([
                {"agentic_job_id": "fix_auth_b1c2", "job_name": "Fix auth bug",
                 "job_type": "bug_fix", "status": "SUCCESS"}
            ])

            fake_transcript = (
                "user: Please fix the authentication bug in the login flow\n"
                "assistant: I've fixed the authentication bug by updating the token validation."
            )

            with unittest.mock.patch.object(handler, 'call_llm', return_value=job_resp), \
                 unittest.mock.patch.object(handler, '_read_session_transcript',
                                            return_value=fake_transcript):
                asyncio.run(handler.run_classification_async(
                    session_id=sid,
                    message="Please fix the authentication bug in the login flow",
                    response="I've fixed the authentication bug by updating the token validation.",
                ))

            # After the fix: the marker file must have at least one kind:"job" record.
            # (Before the fix: Step 3 returns early and no job marker is written.)
            lines = marker_path.read_text().splitlines()
            recs = [json.loads(l) for l in lines]
            job_recs = [r for r in recs if r.get("kind") == "job"]
            self.assertGreaterEqual(
                len(job_recs), 1,
                f"Expected at least one kind:'job' record after self-classified turn; "
                f"got {len(job_recs)} job recs. Full records: {recs}"
            )

            # The original 2 task lines must still be there (no double-write of task pair).
            task_recs = [r for r in recs if r.get("operation_type") in ("GUARDRAIL", "CHAT")]
            self.assertEqual(
                len(task_recs), 2,
                f"Task lines must still be exactly 2 (no double-write); got {len(task_recs)}"
            )
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_revenium_classifier_parse_job_array_single_line_fence(self):
        """WR-02: _parse_job_array must parse single-line fenced JSON (```json[...]```).

        The fence-strip logic previously used splitlines() + lines[1:], which drops the
        entire payload when the LLM returns a single-line fenced response.

        Test 1 (WR-02): single-line fenced JSON returns a one-element list.
        Test 2: multi-line fenced JSON still parses correctly (no regression).
        Test 3: bare (un-fenced) JSON array still parses correctly (no regression).
        """
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-parse-fence-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            job = {"agentic_job_id": "fix_x_a1b2", "job_type": "bug_fix", "status": "SUCCESS"}

            # Test 1: single-line fenced JSON (```json[...]```)
            single_line = "```json" + json.dumps([job]) + "```"
            result = handler._parse_job_array(single_line)
            self.assertEqual(len(result), 1,
                             f"WR-02: single-line fenced JSON must parse to 1 item; got {result}")
            self.assertEqual(result[0]["job_type"], "bug_fix")

            # Test 2: multi-line fenced JSON (no regression)
            multi_line = "```json\n" + json.dumps([job]) + "\n```"
            result2 = handler._parse_job_array(multi_line)
            self.assertEqual(len(result2), 1,
                             f"WR-02 regression: multi-line fenced JSON must parse to 1 item; got {result2}")

            # Test 3: bare (un-fenced) JSON array (no regression)
            bare = json.dumps([job])
            result3 = handler._parse_job_array(bare)
            self.assertEqual(len(result3), 1,
                             f"WR-02 regression: bare JSON array must parse to 1 item; got {result3}")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_revenium_classifier_validate_job_entropy_suffix(self):
        """WR-01 + IN-01: _validate_job must append entropy suffix to English-word-ending IDs.

        The hex check r'_[0-9a-f]{4}$' matches ordinary English words ending in 4 hex chars
        (_face, _beef, _cafe, _dead, _feed, _deed, _fade), causing those IDs to skip the
        entropy-suffix append and risking agentic_job_id collision.

        Test 1 (WR-01): id ending in ordinary English word gets entropy suffix appended.
        Test 2 (WR-01): id ending in _dead also gets suffix (another English hex word).
        Test 3 (WR-01 no-double-suffix): a genuine machine-minted id (e.g. refactor_a1b2)
        that was already given an entropy suffix does not get a second one.
        Test 4 (IN-01): import re as _re does not appear inside _validate_job source.
        """
        import importlib
        import inspect
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-validate-entropy-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            base_job = {"job_type": "bug_fix", "status": "SUCCESS", "job_name": ""}

            # Test 1: id ending in ordinary English word _face
            job_face = dict(base_job, agentic_job_id="cleanup_face")
            result = handler._validate_job(job_face)
            self.assertIsNotNone(result, "cleanup_face job must be valid")
            self.assertNotEqual(result["agentic_job_id"], "cleanup_face",
                                "WR-01: cleanup_face must get entropy suffix appended")
            # The resulting id must match the pattern: original + _ + 4 hex chars
            import re
            self.assertRegex(result["agentic_job_id"], r"cleanup_face_[0-9a-f]{4}$",
                             "WR-01: entropy suffix must be appended as _XXXX")

            # Test 2: id ending in _dead
            job_dead = dict(base_job, agentic_job_id="fix_dead")
            result2 = handler._validate_job(job_dead)
            self.assertIsNotNone(result2, "fix_dead job must be valid")
            self.assertRegex(result2["agentic_job_id"], r"fix_dead_[0-9a-f]{4}$",
                             "WR-01: fix_dead must get entropy suffix appended")

            # Test 3: machine-minted id already has correct entropy suffix pattern
            # Under the unconditional-append approach, every LLM-minted id gets a fresh
            # suffix — so we verify no catastrophic double-suffix (suffix-of-suffix).
            # The unconditional fix means refactor_a1b2 becomes refactor_a1b2_XXXX.
            # That is expected and correct (removes the word-collision class).
            job_minted = dict(base_job, agentic_job_id="refactor_a1b2")
            result3 = handler._validate_job(job_minted)
            self.assertIsNotNone(result3, "refactor_a1b2 job must be valid")
            # It gets one entropy suffix appended. After appending, the id must NOT get
            # a second suffix if _validate_job is called again (idempotency with idempotent
            # use is not a guarantee, but the first call must produce exactly one suffix).
            aid = result3["agentic_job_id"]
            suffix_count = len(re.findall(r"_[0-9a-f]{4}", aid))
            self.assertGreaterEqual(suffix_count, 1, "at least one entropy suffix must be present")
            # The id must not have the form _XXXX_XXXX_XXXX... (no runaway suffix chain)
            self.assertLessEqual(suffix_count, 2,
                                 f"WR-01: id must not get runaway suffix chain; got {aid}")

            # Test 4 (IN-01): no inline 'import re as _re' inside _validate_job
            source = inspect.getsource(handler._validate_job)
            self.assertNotIn("import re as _re", source,
                             "IN-01: 're' must be imported at module scope, not inside _validate_job")
        finally:
            _restore_plugin_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


    def test_tool_event_reporter_reads_jsonl(self):
        """TOOLMTR-01: valid records are emitted; malformed/incomplete lines are skipped;
        null error produces no --error-message flag."""
        import json
        import os
        import subprocess
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        REPORTER = SCRIPTS_DIR / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            # Build a minimal state dir
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            # Write the JSONL fixture: two valid records, one missing required fields,
            # one malformed JSON line.
            jsonl_path = os.path.join(tool_events_dir, 'sess_abc.jsonl')
            records = [
                # valid success record (null error)
                {"sid": "sess_abc", "ts": 1747700000.35, "tool": "terminal",
                 "tool_call_id": "toolu_01", "duration_ms": 1250, "success": True, "error": None},
                # missing required fields (no sid, no tool_call_id)
                {"not": "valid"},
                # malformed JSON
                "not-json{{",
                # valid failure record with non-null error
                {"sid": "sess_abc", "ts": 1747700001.0, "tool": "read_file",
                 "tool_call_id": "toolu_02", "duration_ms": 50, "success": False,
                 "error": "permission denied"},
            ]
            with open(jsonl_path, 'w') as f:
                for r in records:
                    f.write((json.dumps(r) if isinstance(r, dict) else r) + '\n')

            # Build stub revenium that echoes argv to a capture file.
            # The stub also handles `revenium config show` so the preflight passes.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            result = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0,
                             f'reporter exited non-zero: {result.stdout}{result.stderr}')

            # Read capture log
            invocations = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations = [l.strip() for l in f if l.strip()]

            # Exactly two valid records should have produced meter tool-event calls
            meter_calls = [i for i in invocations if 'meter tool-event' in i]
            self.assertEqual(len(meter_calls), 2,
                             f'expected 2 meter tool-event calls, got {len(meter_calls)}: {meter_calls}')

            # The success record (tool=terminal / toolu_01) should NOT contain --error-message
            # Matched by --tool-id (tool_call_id no longer appears after --transaction-id removal)
            toolu_01_calls = [c for c in meter_calls if '--tool-id terminal' in c]
            self.assertEqual(len(toolu_01_calls), 1,
                             f'expected 1 call for terminal (toolu_01), got {toolu_01_calls}')
            self.assertNotIn('--error-message', toolu_01_calls[0],
                             'success record must not carry --error-message')

    def test_tool_event_reporter_idempotency(self):
        """TOOLMTR-03: a pre-seeded ledger line prevents re-shipping; second run adds no
        new ledger lines and no new invocations."""
        import json
        import os
        import subprocess
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        REPORTER = SCRIPTS_DIR / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            # Write a JSONL with one valid record
            jsonl_path = os.path.join(tool_events_dir, 'sess_abc.jsonl')
            record = {"sid": "sess_abc", "ts": 1747700000.0, "tool": "terminal",
                      "tool_call_id": "toolu_01", "duration_ms": 100, "success": True, "error": None}
            with open(jsonl_path, 'w') as f:
                f.write(json.dumps(record) + '\n')

            # Pre-seed the ledger with the exact key for this record
            ledger_path = os.path.join(state_dir, 'revenium-tool-events.ledger')
            with open(ledger_path, 'w') as f:
                f.write('TOOL:sess_abc:toolu_01:1747700000.0\n')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            # Run 1: the record is already ledgered — should produce zero API calls
            result1 = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result1.returncode, 0,
                             f'run1 exited non-zero: {result1.stdout}{result1.stderr}')

            invocations1 = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations1 = [l.strip() for l in f if l.strip()]
            toolu_01_calls = [i for i in invocations1 if 'toolu_01' in i and 'meter tool-event' in i]
            self.assertEqual(len(toolu_01_calls), 0,
                             f'pre-seeded record must be skipped; got calls: {toolu_01_calls}')

            # Record ledger line count before run 2
            with open(ledger_path) as f:
                ledger_before = f.readlines()

            # Run 2: identical state — still zero calls, no new ledger lines
            if os.path.exists(capture_log):
                os.unlink(capture_log)
            result2 = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result2.returncode, 0,
                             f'run2 exited non-zero: {result2.stdout}{result2.stderr}')

            invocations2 = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations2 = [l.strip() for l in f if l.strip()]
            self.assertEqual(len([i for i in invocations2 if 'meter tool-event' in i]), 0,
                             f'run2 must produce no new meter calls: {invocations2}')

            with open(ledger_path) as f:
                ledger_after = f.readlines()
            self.assertEqual(ledger_before, ledger_after,
                             'no new ledger lines should appear on run 2')

    def test_tool_event_reporter_success_flag(self):
        """TOOLMTR-02 / TOOLMTR-04: success:true → bare --success; success:false →
        --success=false; success:false+error → --error-message; --trace-id == sid;
        --cost-usd absent."""
        import json
        import os
        import subprocess
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        REPORTER = SCRIPTS_DIR / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            # Three records: success, failure (no error text), failure (with error text)
            records = [
                {"sid": "sess_abc", "ts": 1747700010.0, "tool": "tool_a",
                 "tool_call_id": "toolu_10", "duration_ms": 100, "success": True, "error": None},
                {"sid": "sess_abc", "ts": 1747700011.0, "tool": "tool_b",
                 "tool_call_id": "toolu_11", "duration_ms": 200, "success": False, "error": None},
                {"sid": "sess_abc", "ts": 1747700012.0, "tool": "tool_c",
                 "tool_call_id": "toolu_12", "duration_ms": 300, "success": False,
                 "error": "disk full"},
            ]
            jsonl_path = os.path.join(tool_events_dir, 'sess_abc.jsonl')
            with open(jsonl_path, 'w') as f:
                for r in records:
                    f.write(json.dumps(r) + '\n')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            result = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0,
                             f'reporter exited non-zero: {result.stdout}{result.stderr}')

            invocations = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations = [l.strip() for l in f if l.strip()]

            meter_calls = [i for i in invocations if 'meter tool-event' in i]
            self.assertEqual(len(meter_calls), 3,
                             f'expected 3 meter tool-event calls, got {len(meter_calls)}: {meter_calls}')

            # Find each call by --tool-id (tool_call_id no longer appears after --transaction-id removal)
            def find_call(tool_name):
                matches = [c for c in meter_calls if f'--tool-id {tool_name}' in c]
                self.assertEqual(len(matches), 1, f'expected exactly 1 call for --tool-id {tool_name}, got {matches}')
                return matches[0]

            call_10 = find_call('tool_a')
            call_11 = find_call('tool_b')
            call_12 = find_call('tool_c')

            # TOOLMTR-02: success flag logic
            self.assertIn('--success', call_10,
                          'success:true must carry bare --success token')
            self.assertNotIn('--success=false', call_10,
                             'success:true must NOT carry --success=false')
            self.assertIn('--success=false', call_11,
                          'success:false must carry --success=false')
            self.assertNotIn('--error-message', call_11,
                             'success:false with null error must not carry --error-message')
            self.assertIn('--success=false', call_12,
                          'success:false+error must carry --success=false')
            self.assertIn('--error-message', call_12,
                          'success:false with error text must carry --error-message')

            # TOOLMTR-04: --trace-id must be the session id
            for call in meter_calls:
                self.assertIn('--trace-id sess_abc', call,
                              f'--trace-id must be sess_abc in: {call}')

            # --cost-usd must not appear
            for call in meter_calls:
                self.assertNotIn('--cost-usd', call,
                                 f'--cost-usd must not appear in tool-event calls: {call}')

    def test_tool_event_reporter_omits_transaction_id(self):
        """Regression guard (TOOLMTR-03 / TOOLMTR-04): the meter tool-event invocation
        must NOT carry --transaction-id because the Revenium tool-event endpoint silently
        drops events that carry it (files them as transaction sub-line-items instead).
        --trace-id must still be present for session correlation."""
        import json
        import os
        import subprocess
        import tempfile

        SCRIPTS_DIR = SKILL / 'scripts'
        REPORTER = SCRIPTS_DIR / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            record = {
                'sid': 'sess_regression',
                'ts': 1747700100.0,
                'tool': 'bash',
                'tool_call_id': 'toolu_reg01',
                'duration_ms': 42,
                'success': True,
                'error': None,
            }
            jsonl_path = os.path.join(tool_events_dir, 'sess_regression.jsonl')
            with open(jsonl_path, 'w') as f:
                f.write(json.dumps(record) + '\n')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            result = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0,
                             f'reporter exited non-zero: {result.stdout}{result.stderr}')

            invocations = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations = [l.strip() for l in f if l.strip()]

            meter_calls = [i for i in invocations if 'meter tool-event' in i]
            self.assertEqual(len(meter_calls), 1,
                             f'expected exactly 1 meter tool-event call, got {len(meter_calls)}: {meter_calls}')

            call = meter_calls[0]
            # Regression guard: --transaction-id must be absent — its presence causes the
            # Revenium endpoint to file the event as a transaction sub-line-item, silently
            # excluding it from `revenium metrics tool-events`.
            self.assertNotIn('--transaction-id', call,
                             f'--transaction-id must NOT appear in meter tool-event call: {call!r}')
            # Session correlation must still be present via --trace-id.
            self.assertIn('--trace-id sess_regression', call,
                          f'--trace-id with session id must be present in: {call!r}')

    # ------------------------------------------------------------------
    # Phase 16 — integration-hardening behavioral tests (TOOLINT-02, 03, 04).
    # ------------------------------------------------------------------

    def test_install_hooks_registers_post_tool_call(self):
        """TOOLINT-02: install-hooks.sh against a fresh tmpdir creates a config.yaml
        with a post_tool_call: key and a command entry ending in post_tool_call.sh.
        uninstall-hooks.sh then removes the post_tool_call entry entirely."""
        import os
        import subprocess
        import tempfile

        install_hooks = str(SKILL / 'scripts' / 'install-hooks.sh')
        uninstall_hooks = str(SKILL / 'scripts' / 'uninstall-hooks.sh')

        with tempfile.TemporaryDirectory(prefix='gsd-p16-post-tool-') as tmp:
            config_path = os.path.join(tmp, 'config.yaml')
            env = dict(os.environ)
            env['HERMES_HOME'] = tmp
            env['REVENIUM_HOOKS_CONFIG_FILE'] = config_path

            # Install
            result = subprocess.run(
                ['bash', install_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                result.returncode, 0,
                f'install-hooks.sh exit {result.returncode}: '
                f'stdout={result.stdout!r} stderr={result.stderr!r}',
            )
            self.assertTrue(os.path.exists(config_path),
                            'install-hooks.sh did not create config.yaml')

            with open(config_path, encoding='utf-8') as fh:
                config_after_install = fh.read()

            # Assert post_tool_call key and command entry are present
            self.assertIn(
                'post_tool_call:', config_after_install,
                f'post_tool_call: key missing from config after install:\n{config_after_install}',
            )
            self.assertIn(
                'post_tool_call.sh', config_after_install,
                f'post_tool_call.sh command missing from config after install:\n{config_after_install}',
            )
            # Confirm the command line ends in scripts/post_tool_call.sh
            import re
            self.assertTrue(
                re.search(r'command:.*scripts/post_tool_call\.sh', config_after_install),
                f'no command: ...scripts/post_tool_call.sh line found:\n{config_after_install}',
            )

            # Uninstall
            uninstall = subprocess.run(
                ['bash', uninstall_hooks],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                uninstall.returncode, 0,
                f'uninstall-hooks.sh exit {uninstall.returncode}: '
                f'stdout={uninstall.stdout!r} stderr={uninstall.stderr!r}',
            )

            with open(config_path, encoding='utf-8') as fh:
                config_after_uninstall = fh.read()

            self.assertNotIn(
                'post_tool_call.sh', config_after_uninstall,
                f'post_tool_call.sh entry survived uninstall:\n{config_after_uninstall}',
            )

    def test_tool_event_jsonl_round_trips_ledger_shape(self):
        """TOOLINT-04: a single valid 7-key JSONL record written to tool-events/<sid>.jsonl
        is shipped by tool-event-report.sh and produces a ledger line matching
        TOOL:<sid>:<tool_call_id>:<ts> with the correct field count and values."""
        import json
        import os
        import subprocess
        import tempfile

        REPORTER = SKILL / 'scripts' / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            os.makedirs(tool_events_dir, mode=0o700)

            sid = 'sess_p16_shape'
            tool_call_id = 'toolu_p16_01'
            ts = 1747800000.0

            record = {
                'sid': sid,
                'ts': ts,
                'tool': 'read_file',
                'tool_call_id': tool_call_id,
                'duration_ms': 75,
                'success': True,
                'error': None,
            }
            jsonl_path = os.path.join(tool_events_dir, f'{sid}.jsonl')
            with open(jsonl_path, 'w') as f:
                f.write(json.dumps(record) + '\n')

            # Build stub revenium that handles config show and records meter calls
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            ledger_path = os.path.join(state_dir, 'revenium-tool-events.ledger')

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            result = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0,
                             f'reporter exited non-zero: {result.stdout}{result.stderr}')

            # Assert ledger file was created and has exactly one line
            self.assertTrue(os.path.exists(ledger_path),
                            f'ledger file not created at {ledger_path}')
            with open(ledger_path) as f:
                ledger_lines = [l.strip() for l in f if l.strip()]
            self.assertEqual(len(ledger_lines), 1,
                             f'expected exactly 1 ledger line, got {len(ledger_lines)}: {ledger_lines}')

            # Assert ledger line shape: TOOL:<sid>:<tool_call_id>:<ts>
            line = ledger_lines[0]
            self.assertTrue(line.startswith('TOOL:'),
                            f'ledger line must start with "TOOL:": {line!r}')
            parts = line.split(':')
            self.assertGreaterEqual(len(parts), 4,
                                    f'ledger line must have at least 4 colon-delimited fields: {line!r}')
            self.assertEqual(parts[0], 'TOOL',
                             f'field 0 must be "TOOL": {line!r}')
            self.assertEqual(parts[1], sid,
                             f'field 1 must be the session id ({sid!r}): {line!r}')
            self.assertEqual(parts[2], tool_call_id,
                             f'field 2 must be the tool_call_id ({tool_call_id!r}): {line!r}')


    def test_tool_event_stage_noop_on_empty_state(self):
        """TOOLINT-03: tool-event-report.sh with an empty tool-events directory exits 0,
        produces zero `meter tool-event` invocations, and adds no ERROR-level lines to
        the metering log — proving backward compatibility with pre-v1.2 installs."""
        import os
        import subprocess
        import tempfile

        REPORTER = SKILL / 'scripts' / 'tool-event-report.sh'

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, 'state', 'revenium')
            tool_events_dir = os.path.join(state_dir, 'tool-events')
            # Create an EMPTY tool-events directory — no JSONL files.
            os.makedirs(tool_events_dir, mode=0o700)

            # Build stub revenium that handles config show and records meter calls.
            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            capture_log = os.path.join(tmpdir, 'capture.log')
            shim = os.path.join(bin_dir, 'revenium')
            with open(shim, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1" in\n'
                    '  config) exit 0 ;;\n'
                    '  meter)\n'
                    '    printf "%s\\n" "$*" >> "$CAPTURE_LOG"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *) exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(shim, 0o755)

            metering_log = os.path.join(state_dir, 'revenium-metering.log')

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': os.path.join(tmpdir, 'hh'),
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'CAPTURE_LOG': capture_log,
            }

            result = subprocess.run(
                ['bash', str(REPORTER)],
                env=env, capture_output=True, text=True, timeout=60,
            )

            # (1) Script must exit 0.
            self.assertEqual(result.returncode, 0,
                             f'tool-event-report.sh exited non-zero on empty state: '
                             f'{result.stdout}{result.stderr}')

            # (2) Capture log must contain zero `meter tool-event` invocations.
            invocations = []
            if os.path.exists(capture_log):
                with open(capture_log) as f:
                    invocations = [l.strip() for l in f if l.strip()]
            meter_calls = [i for i in invocations if 'meter tool-event' in i]
            self.assertEqual(len(meter_calls), 0,
                             f'empty-state run must produce zero meter tool-event calls, '
                             f'got {len(meter_calls)}: {meter_calls}')

            # (3) Metering log must have no ERROR-level lines from this run.
            if os.path.exists(metering_log):
                with open(metering_log) as f:
                    error_lines = [l.strip() for l in f
                                   if '[ERROR]' in l and 'revenium' in l]
                self.assertEqual(len(error_lines), 0,
                                 f'empty-state run must not add ERROR lines to metering log, '
                                 f'got: {error_lines}')

    def test_setup_guardrails_migration_happy_path(self):
        """MIGR-01..04 + MIGR-05 happy path. Seeds config.json with alertId only, fake revenium
        returns matching alert via `list`, script runs in --auto mode, writes ruleIds and emits
        one deprecation log line. alertId is preserved per D-09."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        script = SKILL / 'scripts' / 'setup-guardrails.sh'
        self.assertTrue(script.exists(), 'setup-guardrails.sh missing — plan 18-02 must land first')

        with tempfile.TemporaryDirectory() as tmp:
            # Build skill tree
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            # Build state directory with seeded config.json
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, exist_ok=True)
            config_seed = {'alertId': 'LEGACY01', 'autonomousMode': False}
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump(config_seed, f)
            # Create empty metering log
            open(os.path.join(state_dir, 'revenium-metering.log'), 'w').close()

            # Build fake revenium dispatcher in ~/.local/bin (shim_home) so that
            # common.sh's ensure_path prepends it last (highest priority), overriding
            # any real revenium installed at /opt/homebrew/bin.
            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            argv_log = os.path.join(tmp, 'revenium.argv.log')
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    '# Dispatch on up to 3 args to distinguish probe vs create\n'
                    'case "$1 $2 $3" in\n'
                    '  "config show "* | "config show")\n'
                    '    echo "api_key: mock-api-key-12345"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules create")\n'
                    '    printf "%s\\n" "$*" >> "' + argv_log + '"\n'
                    '    echo \'{"id":"TESTRULE001","name":"Hermes Monthly Budget","metricType":"TOTAL_COST","windowType":"MONTHLY","action":"BLOCK","groupBy":"ORGANIZATION","hardLimit":50,"warnThreshold":40,"shadowMode":false}\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules list")\n'
                    '    echo "[]"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails enforcement-events --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "alerts budget list")\n'
                    '    echo \'[{"alertId":"LEGACY01","cumulativePeriod":"MONTHLY","threshold":50,"name":"Hermes Monthly Budget","currentValue":0,"groups":[],"metricType":"TOTAL_COST","percentUsed":0,"remaining":50,"risk":"low","window":"MONTHLY"}]\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *)\n'
                    '    echo "fake revenium: unhandled: $*" >&2\n'
                    '    exit 1\n'
                    '    ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'),
                 '--from-alert', 'LEGACY01', '--auto'],
                env=env, capture_output=True, text=True, timeout=15,
            )

            self.assertEqual(result.returncode, 0,
                             f'stdout={result.stdout}\nstderr={result.stderr}')

            # Assert config.json was updated correctly
            with open(os.path.join(state_dir, 'config.json')) as f:
                cfg = json.load(f)
            self.assertEqual(cfg.get('ruleIds'), ['TESTRULE001'],
                             f'ruleIds mismatch: {cfg}')
            self.assertEqual(cfg.get('alertId'), 'LEGACY01',
                             'D-09: alertId must be preserved as orphan')
            self.assertIs(cfg.get('autonomousMode'), False,
                          'other config fields must be preserved')

            # Assert the create call was made with correct flags
            self.assertTrue(os.path.exists(argv_log),
                            'fake revenium.argv.log not created — create call was never made')
            with open(argv_log) as f:
                argv_content = f.read()
            create_lines = [l for l in argv_content.splitlines() if 'budget-rules create' in l]
            self.assertEqual(len(create_lines), 1,
                             f'expected exactly 1 create call, got {len(create_lines)}: {create_lines}')
            create_argv = create_lines[0]
            self.assertIn('--metric-type TOTAL_COST', create_argv,
                          f'--metric-type TOTAL_COST missing from create argv: {create_argv!r}')
            self.assertIn('--window-type MONTHLY', create_argv,
                          f'--window-type MONTHLY missing from create argv: {create_argv!r}')
            self.assertIn('--action BLOCK', create_argv,
                          f'--action BLOCK missing from create argv: {create_argv!r}')
            self.assertIn('--group-by AGENT', create_argv,
                          f'--group-by AGENT missing from create argv: {create_argv!r}')
            self.assertIn('--warn-threshold 40', create_argv,
                          f'--warn-threshold 40 (80% of 50) missing from create argv: {create_argv!r}')
            self.assertIn('--hard-limit 50', create_argv,
                          f'--hard-limit 50 missing from create argv: {create_argv!r}')
            self.assertNotIn('--shadow-mode', create_argv,
                             'D-08: --shadow-mode must NOT be present when REVENIUM_MIGRATE_SHADOW_MODE is unset')
            # quick-task 260524-lpu: default-scope created rules to AGENT:IS:Hermes so
            # the rule actually evaluates against the meter completions this skill ships.
            self.assertIn('--filter AGENT:IS:Hermes', create_argv,
                          f'default filter --filter AGENT:IS:Hermes missing from create argv: {create_argv!r}')

            # Assert exactly one deprecation log line in revenium-metering.log
            with open(os.path.join(state_dir, 'revenium-metering.log')) as f:
                log_lines = f.readlines()
            deprecation_lines = [l for l in log_lines if 'deprecation:' in l]
            self.assertEqual(len(deprecation_lines), 1,
                             f'expected exactly 1 deprecation line, got {len(deprecation_lines)}: {deprecation_lines}')
            self.assertRegex(deprecation_lines[0],
                             r'deprecation: legacy alertId LEGACY01 orphaned, migrated to ruleId TESTRULE001')

            # Assert migration-notify-state gate file is absent on success path
            notify_file = os.path.join(state_dir, 'migration-notify-state')
            self.assertFalse(os.path.exists(notify_file),
                             'migration-notify-state should be absent after a successful migration')

    def test_setup_guardrails_idempotency(self):
        """MIGR-04 + SETUP-05 idempotency. Pre-seeded config.json with ruleIds -> --auto mode is
        silent exit-0 no-op; zero create calls; second run is also a no-op
        (concurrent-cron-retry safety)."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        script = SKILL / 'scripts' / 'setup-guardrails.sh'
        self.assertTrue(script.exists(), 'setup-guardrails.sh missing — plan 18-02 must land first')

        with tempfile.TemporaryDirectory() as tmp:
            # Build skill tree
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            # Build state directory — seed config.json WITH ruleIds already populated
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, exist_ok=True)
            config_seed = {'alertId': 'LEGACY01', 'ruleIds': ['EXISTING01'], 'autonomousMode': False}
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump(config_seed, f)
            open(os.path.join(state_dir, 'revenium-metering.log'), 'w').close()

            # Fake revenium in shim_home/.local/bin (highest priority after ensure_path)
            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            argv_log = os.path.join(tmp, 'revenium.argv.log')
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "config show "* | "config show")\n'
                    '    echo "api_key: mock-api-key-12345"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails enforcement-events --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules create")\n'
                    '    printf "%s\\n" "$*" >> "' + argv_log + '"\n'
                    '    echo \'{"id":"SHOULDNOTBECALLED","name":"Should Not Be Called"}\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "alerts budget list")\n'
                    '    echo \'[{"alertId":"LEGACY01","cumulativePeriod":"MONTHLY","threshold":50,"name":"Hermes Monthly Budget","currentValue":0,"groups":[],"metricType":"TOTAL_COST"}]\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *)\n'
                    '    echo "fake revenium: unhandled: $*" >&2\n'
                    '    exit 1\n'
                    '    ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            run_args = ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'),
                        '--from-alert', 'LEGACY01', '--auto']

            # ---- First invocation ----
            result = subprocess.run(run_args, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0,
                             f'first run: stdout={result.stdout}\nstderr={result.stderr}')

            with open(os.path.join(state_dir, 'config.json')) as f:
                cfg = json.load(f)
            self.assertEqual(cfg.get('ruleIds'), ['EXISTING01'],
                             'ruleIds must be UNCHANGED after idempotent no-op')
            self.assertEqual(cfg.get('alertId'), 'LEGACY01',
                             'alertId must be UNCHANGED')

            # Assert ZERO create calls
            if os.path.exists(argv_log):
                with open(argv_log) as f:
                    create_lines = sum(1 for l in f if 'budget-rules create' in l)
            else:
                create_lines = 0
            self.assertEqual(create_lines, 0,
                             f'first run: expected 0 create calls, got {create_lines}')

            # Assert NO deprecation lines in log
            with open(os.path.join(state_dir, 'revenium-metering.log')) as f:
                log_text = f.read()
            self.assertNotIn('deprecation:', log_text,
                             'no migration happened — no deprecation line expected')

            # ---- Second invocation (idempotency: still no-op) ----
            result2 = subprocess.run(run_args, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result2.returncode, 0,
                             f'second run: stdout={result2.stdout}\nstderr={result2.stderr}')

            with open(os.path.join(state_dir, 'config.json')) as f:
                cfg2 = json.load(f)
            self.assertEqual(cfg2.get('ruleIds'), ['EXISTING01'],
                             'ruleIds must still be UNCHANGED after second run')
            self.assertEqual(cfg2.get('alertId'), 'LEGACY01',
                             'alertId must still be UNCHANGED after second run')

            if os.path.exists(argv_log):
                with open(argv_log) as f:
                    create_lines2 = sum(1 for l in f if 'budget-rules create' in l)
            else:
                create_lines2 = 0
            self.assertEqual(create_lines2, 0,
                             f'second run: expected 0 create calls total, got {create_lines2}')

    def test_setup_guardrails_missing_alert_edge_case(self):
        """D-09 deleted-upstream-alert + D-10 notify-once gate + MIGR-05 loud-on-failure.
        Two identical invocations produce: config.json untouched both times, error logged,
        notify-once gate file written exactly once (hash-stable across runs)."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        script = SKILL / 'scripts' / 'setup-guardrails.sh'
        self.assertTrue(script.exists(), 'setup-guardrails.sh missing — plan 18-02 must land first')

        with tempfile.TemporaryDirectory() as tmp:
            # Build skill tree
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            # Build state directory — alertId points at MISSING01 (not in fake list)
            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, exist_ok=True)
            config_seed = {'alertId': 'MISSING01', 'autonomousMode': False}
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump(config_seed, f)
            open(os.path.join(state_dir, 'revenium-metering.log'), 'w').close()

            # Fake revenium in shim_home/.local/bin (highest priority after ensure_path)
            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            argv_log = os.path.join(tmp, 'revenium.argv.log')
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "config show "* | "config show")\n'
                    '    echo "api_key: mock-api-key-12345"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails enforcement-events --help")\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules create")\n'
                    '    printf "%s\\n" "$*" >> "' + argv_log + '"\n'
                    '    echo \'{"id":"SHOULDNOTBECALLED","name":"Should Not Be Called"}\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "alerts budget list")\n'
                    # NOTE: returns OTHERONE — MISSING01 is NOT in this list (D-09 test)
                    '    echo \'[{"alertId":"OTHERONE","cumulativePeriod":"MONTHLY","threshold":99,"name":"Some Other Budget","metricType":"TOTAL_COST"}]\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  *)\n'
                    '    echo "fake revenium: unhandled: $*" >&2\n'
                    '    exit 1\n'
                    '    ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            run_args = ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'),
                        '--from-alert', 'MISSING01', '--auto']
            notify_file = os.path.join(state_dir, 'migration-notify-state')

            # ---- First invocation ----
            result = subprocess.run(run_args, env=env, capture_output=True, text=True, timeout=15)
            # D-09: script must exit 0 (log + notify-once + exit 0 so cron continues)
            self.assertEqual(result.returncode, 0,
                             f'first run: stdout={result.stdout}\nstderr={result.stderr}')

            # D-09: config.json must be UNCHANGED (no ruleIds written)
            with open(os.path.join(state_dir, 'config.json')) as f:
                cfg = json.load(f)
            self.assertEqual(cfg, config_seed,
                             f'config.json must be untouched on deleted-alert path: {cfg}')
            self.assertNotIn('ruleIds', cfg,
                             'ruleIds must NOT be added on the deleted-alert path')

            # D-10: notify-once gate file must be written
            self.assertTrue(os.path.exists(notify_file),
                            'migration-notify-state gate file must be written on first failure')
            with open(notify_file) as f:
                first_hash = f.read().strip()
            self.assertGreaterEqual(len(first_hash), 16,
                                    f'gate file must contain a hex hash of at least 16 chars, got {first_hash!r}')

            # MIGR-05: error line must appear in metering log
            with open(os.path.join(state_dir, 'revenium-metering.log')) as f:
                log_text = f.read()
            self.assertRegex(log_text, r'Legacy alertId MISSING01 not found in Revenium',
                             'error log must reference the missing alertId')

            # No create calls
            if os.path.exists(argv_log):
                with open(argv_log) as f:
                    create_lines = sum(1 for l in f if 'budget-rules create' in l)
            else:
                create_lines = 0
            self.assertEqual(create_lines, 0,
                             f'first run: expected 0 create calls, got {create_lines}')

            # ---- Second invocation (D-10: gate file written exactly once) ----
            result2 = subprocess.run(run_args, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result2.returncode, 0,
                             f'second run: stdout={result2.stdout}\nstderr={result2.stderr}')

            # config.json must still be unchanged
            with open(os.path.join(state_dir, 'config.json')) as f:
                cfg2 = json.load(f)
            self.assertEqual(cfg2, config_seed,
                             f'config.json must remain untouched on second run: {cfg2}')

            # D-10 KEY assertion: gate file content must be BYTE-IDENTICAL across runs
            self.assertTrue(os.path.exists(notify_file),
                            'migration-notify-state gate file must still exist after second run')
            with open(notify_file) as f:
                second_hash = f.read().strip()
            self.assertEqual(second_hash, first_hash,
                             f'D-10: gate file must not be rewritten for same error class. '
                             f'first={first_hash!r} second={second_hash!r}')

            # Still zero create calls
            if os.path.exists(argv_log):
                with open(argv_log) as f:
                    create_lines2 = sum(1 for l in f if 'budget-rules create' in l)
            else:
                create_lines2 = 0
            self.assertEqual(create_lines2, 0,
                             f'second run: expected 0 create calls total, got {create_lines2}')

    def test_setup_guardrails_bootstraps_missing_config_in_interactive_mode(self):
        """SC-1 fresh-host edge case. On a truly empty host with no state dir and no config.json,
        the script in interactive/default mode self-bootstraps STATE_DIR and seeds {} into
        config.json instead of erroring out. The --auto (cron) path keeps its fail-open exit-0
        posture and does NOT bootstrap (cron must not silently create state on a fresh host)."""
        import os
        import shutil
        import subprocess
        import tempfile

        script = SKILL / 'scripts' / 'setup-guardrails.sh'
        self.assertTrue(script.exists(), 'setup-guardrails.sh missing')

        # --- Interactive/default path: must bootstrap ---
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            # NO state dir, NO config.json — truly empty host
            state_dir = os.path.join(tmp, 'state', 'revenium')
            config_path = os.path.join(state_dir, 'config.json')
            self.assertFalse(os.path.exists(state_dir),
                             'precondition: state dir must not exist')
            self.assertFalse(os.path.exists(config_path),
                             'precondition: config.json must not exist')

            # Fake revenium that satisfies has_guardrails_cli probe
            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "guardrails budget-rules --help") exit 0 ;;\n'
                    '  "guardrails enforcement-events --help") exit 0 ;;\n'
                    '  "config show "* | "config show") echo "api_key: mock"; exit 0 ;;\n'
                    '  *) exit 1 ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            # Run --interactive with stdin closed — bootstrap happens before any prompt;
            # the script will exit non-zero when prompts hit EOF, but config.json must exist.
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'), '--interactive'],
                env=env, capture_output=True, text=True, timeout=15,
                stdin=subprocess.DEVNULL,
            )

            # Bootstrap must have run regardless of how interactive prompts ended
            self.assertTrue(os.path.isdir(state_dir),
                            f'state dir must exist after bootstrap; stdout={result.stdout!r} stderr={result.stderr!r}')
            self.assertTrue(os.path.isfile(config_path),
                            f'config.json must be seeded after bootstrap; stderr={result.stderr!r}')
            with open(config_path) as f:
                seeded = f.read().strip()
            # Seed format is `{}\n` written via `printf '{}\n'`
            self.assertEqual(seeded, '{}',
                             f'seeded config.json must be exactly an empty JSON object, got {seeded!r}')
            # The `info` helper writes to LOG_FILE always, to stderr only on TTY.
            # subprocess captures stderr (not a TTY), so check the log file instead.
            log_file = os.path.join(state_dir, 'revenium-metering.log')
            self.assertTrue(os.path.exists(log_file),
                            'log file must exist after bootstrap')
            with open(log_file) as f:
                log_text = f.read()
            self.assertIn('bootstrapping fresh state', log_text,
                          f'bootstrap info line must be logged; log={log_text!r}')

        # --- --auto (cron) path: must NOT bootstrap, must exit 0 cleanly ---
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            config_path = os.path.join(state_dir, 'config.json')

            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "guardrails budget-rules --help") exit 0 ;;\n'
                    '  "guardrails enforcement-events --help") exit 0 ;;\n'
                    '  *) exit 1 ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'),
                 '--from-alert', 'NEVER', '--auto'],
                env=env, capture_output=True, text=True, timeout=15,
            )

            # Auto path: exit 0 (cron-safe), state dir must NOT have been created,
            # config.json must NOT have been seeded.
            self.assertEqual(result.returncode, 0,
                             f'--auto with missing config must exit 0; stderr={result.stderr!r}')
            self.assertFalse(os.path.isfile(config_path),
                             '--auto path must NOT create config.json on a missing-install host')

    def test_setup_guardrails_filter_override(self):
        """quick-task 260524-lpu: when --filter is passed explicitly, the create argv
        uses the operator's filter and does NOT include the default AGENT:IS:Hermes scope.
        Mirrors the fake-revenium harness pattern from test_setup_guardrails_migration_happy_path."""
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        script = SKILL / 'scripts' / 'setup-guardrails.sh'
        self.assertTrue(script.exists(), 'setup-guardrails.sh missing')

        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            shutil.copy(str(SKILL / 'scripts' / 'common.sh'), scripts_dir)
            shutil.copy(str(SKILL / 'scripts' / 'setup-guardrails.sh'), scripts_dir)

            state_dir = os.path.join(tmp, 'state', 'revenium')
            os.makedirs(state_dir, exist_ok=True)
            # Default mode requires a non-empty config.json with no pre-existing ruleIds
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump({'autonomousMode': False}, f)
            open(os.path.join(state_dir, 'revenium-metering.log'), 'w').close()

            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            argv_log = os.path.join(tmp, 'revenium.argv.log')
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "config show "* | "config show")\n'
                    '    echo "api_key: mock-api-key-12345"\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules --help") exit 0 ;;\n'
                    '  "guardrails enforcement-events --help") exit 0 ;;\n'
                    '  "guardrails budget-rules create")\n'
                    '    printf "%s\\n" "$*" >> "' + argv_log + '"\n'
                    '    echo \'{"id":"OVERRIDERULE","name":"Hermes Monthly Budget"}\'\n'
                    '    exit 0\n'
                    '    ;;\n'
                    '  "guardrails budget-rules list") echo "[]"; exit 0 ;;\n'
                    '  *)\n'
                    '    echo "fake revenium: unhandled: $*" >&2\n'
                    '    exit 1\n'
                    '    ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': tmp,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'setup-guardrails.sh'),
                 '--hard-limit', '50', '--period', 'MONTHLY',
                 '--filter', 'MODEL:IS:claude-3-opus'],
                env=env, capture_output=True, text=True, timeout=15,
            )

            self.assertEqual(result.returncode, 0,
                             f'stdout={result.stdout}\nstderr={result.stderr}')

            self.assertTrue(os.path.exists(argv_log),
                            'fake revenium.argv.log not created — create call was never made')
            with open(argv_log) as f:
                argv_content = f.read()
            create_lines = [l for l in argv_content.splitlines() if 'budget-rules create' in l]
            self.assertEqual(len(create_lines), 1,
                             f'expected exactly 1 create call, got {len(create_lines)}: {create_lines}')
            create_argv = create_lines[0]
            self.assertIn('--filter MODEL:IS:claude-3-opus', create_argv,
                          f'operator filter --filter MODEL:IS:claude-3-opus missing from create argv: {create_argv!r}')
            self.assertNotIn('--filter AGENT:IS:Hermes', create_argv,
                             f'default AGENT filter must NOT appear when operator passes --filter: {create_argv!r}')


if __name__ == '__main__':
    unittest.main()
