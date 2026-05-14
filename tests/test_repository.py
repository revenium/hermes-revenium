import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
PLUGIN_DIR = SKILL / 'plugins' / 'revenium-classifier'


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
        'REVENIUM_TAXONOMY_FILE',
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
            # Phase 6 — on_session_end classifier plugin (HOOK-01, HOOK-11)
            SKILL / 'plugins' / 'revenium-classifier' / 'plugin.yaml',
            SKILL / 'plugins' / 'revenium-classifier' / '__init__.py',
            SKILL / 'plugins' / 'revenium-classifier' / 'classifier.py',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'trivial-turn.json',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'substantive-turn.json',
            SKILL / 'plugins' / 'revenium-classifier' / 'test-payloads' / 'subagent-turn.json',
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
            if re.search(r'OpenClaw|openclaw|ClawHub|clawhub', text):
                offenders.append(str(rel))
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
        # Phase 3 D-13: LOCK_FILE declared in common.sh (single source of truth);
        # never hardcoded in cron.sh or hermes-report.sh.
        self.assertIn('LOCK_FILE=', text)
        self.assertIn('cron.lock', text)

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
                    os.unlink(os.path.join(markers_dir, f_))

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
                os.unlink(os.path.join(markers_dir, f_))

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
            self.assertNotIn('--operation-type', flags,
                             'zero-marker fallthrough must NOT emit --operation-type '
                             '(Phase 4 WIRE-01 owns that decision)')
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
                os.unlink(os.path.join(markers_dir, f_))

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

            combined = result.stdout + result.stderr
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

    def test_revenium_classifier_trivial_skip(self):
        """HOOK-02 / D-07: a turn with no tools in the session jsonl AND response < 200 chars
        must skip marker write — no file created."""
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
            # No session jsonl exists in tmp HERMES_HOME → _count_tools_in_current_turn returns 0
            asyncio.run(handler.run_classification_async(
                session_id=context['session_id'],
                message=context.get('message'),
                response=context.get('response'),
                model=context.get('model'),
                platform=context.get('platform'),
            ))
            self.assertFalse(
                (handler.MARKERS_DIR / f"{context['session_id']}.jsonl").exists(),
                "trivial turn must NOT create marker file (HOOK-02 / D-07)",
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

            # Patch call_llm so we can prove it was NOT called
            with unittest.mock.patch.object(handler, 'call_llm') as mock_llm:
                mock_llm.side_effect = AssertionError("LLM must NOT be called when agent already wrote markers")
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

            # Marker file should still have exactly 2 lines (no hook-added lines)
            lines = marker_path.read_text().splitlines()
            self.assertEqual(len(lines), 2, f"hook double-wrote; got {len(lines)} lines")

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
            with unittest.mock.patch.object(handler, 'call_llm', return_value=mock_resp):
                asyncio.run(handler.run_classification_async(
                    session_id=context['session_id'],
                    message=context.get('message'),
                    response=context.get('response'),
                    model=context.get('model'),
                    platform=context.get('platform'),
                ))
            # Now marker file has 4 lines (2 stale + 2 new from hook)
            lines = marker_path.read_text().splitlines()
            self.assertEqual(len(lines), 4)
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

    def test_revenium_classifier_halt_unclassified(self):
        """HOOK-04 / D-08: when budget-status.json::halted is True, the LLM is NOT called
        and a marker pair with task_type=unclassified is written."""
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

            # Seed a halted budget-status.json
            os.makedirs(sd, exist_ok=True)
            with open(os.path.join(sd, 'budget-status.json'), 'w', encoding='utf-8') as f:
                json.dump({"halted": True, "exceeded": True, "currentValue": 99,
                           "threshold": 50, "percentUsed": 198,
                           "haltedAt": "2026-05-13T00:00:00Z",
                           "lastChecked": "2026-05-13T00:00:00Z"}, f)

            self.assertTrue(handler._budget_halted())

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
        """HOOK-04 / D-08: missing budget-status.json returns False from _budget_halted
        (fail-open). The handler must NOT crash and must NOT short-circuit to unclassified."""
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

            # No budget-status.json in tmpdir → fail-open
            self.assertFalse(handler.BUDGET_STATUS_FILE.exists())
            self.assertFalse(handler._budget_halted())
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

    def test_revenium_classifier_substantive_uses_session_jsonl_tool_count(self):
        """HOOK-02 / Pitfall 3: when the session jsonl has tool entries, _count_tools_in_current_turn
        returns the right count and the trivial-skip path does NOT trigger even for short responses."""
        import importlib
        import json
        import os
        import shutil
        import sys
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix='gsd-hook-toolcount-')
        snap, added, hh, sd, md = _setup_plugin_env(tmpdir)
        try:
            if 'classifier' in sys.modules:
                importlib.reload(sys.modules['classifier'])
            import classifier as handler

            sessions_dir = os.path.join(hh, 'sessions')
            os.makedirs(sessions_dir, exist_ok=True)
            sid = "session-with-tools"
            jsonl_path = os.path.join(sessions_dir, f"{sid}.jsonl")
            with open(jsonl_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps({"role": "user", "content": "x"}) + "\n")
                f.write(json.dumps({"role": "tool", "name": "read_file", "content": "..."}) + "\n")
                f.write(json.dumps({"role": "tool", "name": "terminal", "content": "..."}) + "\n")
                f.write(json.dumps({"role": "assistant", "content": "ok"}) + "\n")
            self.assertEqual(handler._count_tools_in_current_turn(sid), 2)
        finally:
            _restore_plugin_env(snap, added)
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
                self.assertEqual(set(r.keys()), {'muid', 'ts', 'sid', 'task_type', 'operation_type'})
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


if __name__ == '__main__':
    unittest.main()
