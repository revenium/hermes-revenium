import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
HOOK_DIR = SKILL / 'hooks' / 'revenium-classifier'


def _agent_aux_client_available() -> bool:
    """True iff `from agent.auxiliary_client import call_llm` succeeds. Phase 6
    hook tests that exercise the real LLM call require this; mocked tests do not."""
    try:
        from agent.auxiliary_client import call_llm  # noqa: F401
        return True
    except ImportError:
        return False


def _setup_hook_env(tmpdir):
    """Returns (env_snapshot, sys_path_added, hermes_home, state_dir, markers_dir).
    Caller must call _restore_hook_env in finally."""
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
    sys_path_added = str(HOOK_DIR) not in sys.path
    if sys_path_added:
        sys.path.insert(0, str(HOOK_DIR))
    return snapshot, sys_path_added, hermes_home, state_dir, markers_dir


def _restore_hook_env(snapshot, sys_path_added):
    import os
    import sys
    if sys_path_added and str(HOOK_DIR) in sys.path:
        sys.path.remove(str(HOOK_DIR))
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
            # Phase 6 — agent:end classifier hook (HOOK-01)
            SKILL / 'hooks' / 'revenium-classifier' / 'HOOK.yaml',
            SKILL / 'hooks' / 'revenium-classifier' / 'handler.py',
            SKILL / 'hooks' / 'revenium-classifier' / 'test-payloads' / 'trivial-turn.json',
            SKILL / 'hooks' / 'revenium-classifier' / 'test-payloads' / 'substantive-turn.json',
            SKILL / 'hooks' / 'revenium-classifier' / 'test-payloads' / 'subagent-turn.json',
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
        snap, added, hh, sd, md = _setup_hook_env(tmpdir)
        try:
            if 'handler' in sys.modules:
                importlib.reload(sys.modules['handler'])
            import handler

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
            _restore_hook_env(snap, added)
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
