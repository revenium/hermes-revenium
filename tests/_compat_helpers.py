"""Shared helpers for COMPAT-01 golden-argv tests.

Extracts the PATH-shim + state.db + shlex round-trip idiom from
test_cron_marker_split_end_to_end (test_repository.py:1024-1417) so the
four per-verb COMPAT-01 tests can stay DRY without duplicating ~80 LoC each.
"""
import json
import os
import re
import shlex
import sqlite3
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPTS_DIR = SKILL / 'scripts'
FIXTURES_DIR = Path(__file__).parent / 'fixtures' / 'compat'


def argv_to_flags(argv):
    """Convert flat argv list to {flag: value} dict for golden assertions.

    Non-flag tokens accumulate as positionals:
      positionals[0] -> __verb
      positionals[1] -> __subcommand
      positionals[2:] -> __positional_args

    Single-token flags (--quiet, --is-streamed, bare --success) store True.
    Two-token pairs store the next token's string value.
    """
    d = {}
    positionals = []
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
            positionals.append(tok)
            i += 1
    if positionals:
        d['__verb'] = positionals[0]
        if len(positionals) > 1:
            d['__subcommand'] = positionals[1]
        if len(positionals) > 2:
            d['__positional_args'] = positionals[2:]
    return d


def load_golden(filename):
    """Load a golden fixture by filename from FIXTURES_DIR.

    Raises FileNotFoundError if the fixture is missing (failing the test
    informatively rather than silently).
    """
    return json.load(open(FIXTURES_DIR / filename))


def assert_argv_matches_golden(test_case, argv, golden):
    """Assert captured argv matches the D-04 allowlist from a golden fixture.

    For each exact_match_fields entry: assertEqual with COMPAT-01 wire drift msg.
    For each pattern_fields entry: assertRegex with COMPAT-01 pattern drift msg.
    For each forbidden_fields entry: assertNotIn with COMPAT-01 forbidden flag msg.
    The error messages include the full argv for debuggability.
    """
    flags = argv_to_flags(argv)

    for field, expected in golden['exact_match_fields'].items():
        actual = flags.get(field)
        test_case.assertEqual(
            actual, expected,
            f'COMPAT-01 wire drift: {field!r} expected {expected!r} got {actual!r}\n'
            f'Full argv: {argv}'
        )

    for field, pattern in golden['pattern_fields'].items():
        actual = flags.get(field, '')
        test_case.assertRegex(
            str(actual), pattern,
            f'COMPAT-01 pattern drift: {field!r} value {actual!r} does not match {pattern!r}'
        )

    for field in golden.get('forbidden_fields', []):
        test_case.assertNotIn(
            field, flags,
            f'COMPAT-01 forbidden flag re-appeared: {field!r} in {argv}'
        )


def build_shim(shim_path, invocations_log=None, jobs_log=None, meter_log=None, tool_log=None):
    """Write a no-shift revenium shim at shim_path and chmod it 0o755.

    NO-SHIFT DESIGN (PATTERNS lines 202-226): the shim captures the FULL argv
    starting with the verb token. Do NOT shift past verb/subcommand — that would
    drop __verb/__subcommand from argv_to_flags output and break the golden asserts.

    Log routing is done via bash env var cascades:
      meter completion  -> ${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}
      meter tool-event  -> ${TOOL_LOG:-${INVOCATIONS_LOG:-/dev/null}}
      jobs              -> ${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}

    Callers pass log paths via subprocess.run env= — bash evaluates the
    ${VAR:-fallback} references at invocation time. If a kwarg is None,
    simply do not set that env var in the subprocess env.

    Branch contracts:
      config)     -> exit 0  (neutralizes hermes-report.sh:29-31 preflight)
      guardrails) -> exit 0  (neutralizes has_guardrails_cli() probes per RESEARCH Pitfall 1 ext)
      meter)      -> JOBS_CLI_CAPABLE probe + subcommand-routed capture
      jobs)       -> bare --help probe + JOBS_LOG-routed capture
      *)          -> exit 0  (default catch-all)
    """
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config) exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  meter)\n'
        '    # Pitfall 2: hermes-report.sh:39 calls `revenium meter completion --help`\n'
        '    # to probe for --agentic-job-id capability. Respond so JOBS_CLI_CAPABLE=1.\n'
        '    if [[ "$3" == "--help" ]]; then\n'
        '      echo "--agentic-job-id  Agentic job instance identifier"\n'
        '      exit 0\n'
        '    fi\n'
        '    case "$2" in\n'
        '      completion)\n'
        '        printf "%q " "$@" >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        printf "\\n"      >> "${METER_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        ;;\n'
        '      tool-event)\n'
        '        printf "%q " "$@" >> "${TOOL_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        printf "\\n"      >> "${TOOL_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '        ;;\n'
        '      *)\n'
        '        printf "%q " "$@" >> "${INVOCATIONS_LOG:-/dev/null}"\n'
        '        printf "\\n"      >> "${INVOCATIONS_LOG:-/dev/null}"\n'
        '        ;;\n'
        '    esac\n'
        '    exit 0\n'
        '    ;;\n'
        '  jobs)\n'
        '    # Pitfall 1: bare `revenium jobs --help` probe per hermes-report.sh.\n'
        '    if [[ "$2" == "--help" ]]; then exit 0; fi\n'
        '    printf "%q " "$@" >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    printf "\\n"      >> "${JOBS_LOG:-${INVOCATIONS_LOG:-/dev/null}}"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


def build_state_db(path, sessions):
    """Create a Hermes sessions DB at path with the production schema.

    Copied verbatim from test_repository.py:1042-1064. Each session dict
    provides: id, model, source, input_tokens, output_tokens, cache_read,
    cache_write, reasoning, estimated_cost, api_calls, started_at, ended_at,
    billing_provider.
    """
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


def run_script(script_path, env, invocations_log):
    """Run a bash script and parse the captured invocations log.

    Returns (returncode, invocations, combined_output) where invocations is
    a list of shlex.split argv lists from invocations_log. Mirrors the
    run_cron pattern from test_repository.py:1078-1097.
    """
    result = subprocess.run(
        ['bash', str(script_path)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    invocations = []
    if os.path.exists(invocations_log):
        with open(invocations_log) as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                invocations.append(shlex.split(line))
    return result.returncode, invocations, result.stdout + result.stderr
