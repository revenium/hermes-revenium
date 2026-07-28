"""Phase 28 Plan 01 — end-to-end tracer for the plugin-registration reason
code (D-07/D-08). Clones the scratch-tree harness shape from
tests.test_repository.RepositoryTests.test_hermes_report_subagent_trace_inheritance:
build a scratch skill-scripts tree, seed state.db with one aged session and NO
marker file, run plugin-status.sh (unregistered fixture, must exit 1), then run
hermes-report.sh and assert revenium-metering.log names
`reason=plugin_unregistered` for that session.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'


class Phase28ReasonCodeTests(unittest.TestCase):
    def test_plugin_unregistered_reason_code_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix='gsd-phase28-01-') as tmp:
            # 1. Scratch skill-scripts tree (mirrors production layout so
            #    SCRIPT_DIR-relative sourcing/sidecar lookups resolve).
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            for name in (
                'common.sh', 'plugin-status.sh', 'hermes-report.sh',
                'get-root-session-id.py', 'split_strategies.py',
            ):
                shutil.copy(str(SKILL / 'scripts' / name), scripts_dir)

            # 2. State directory. No plugins/ directory and no config.yaml
            #    entry — this fixture is deliberately unregistered.
            hermes_home = tmp
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, exist_ok=True)
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump({'organizationName': 'Test Org'}, f)

            # No marker file is written for the session — the classifier
            # never ran, matching the live incident this phase diagnoses.

            # 3. Seed state.db with one session aged past the settle window.
            db_path = os.path.join(hermes_home, 'state.db')
            conn = sqlite3.connect(db_path)
            try:
                conn.execute('''
                    CREATE TABLE sessions (
                        id TEXT PRIMARY KEY, model TEXT, source TEXT,
                        input_tokens INTEGER, output_tokens INTEGER,
                        cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                        reasoning_tokens INTEGER, estimated_cost_usd REAL,
                        api_call_count INTEGER, started_at REAL, ended_at REAL,
                        billing_provider TEXT, parent_session_id TEXT
                    )
                ''')
                now = time.time()
                old_ts = now - 300
                conn.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        'unregistered-sess-1', 'claude-sonnet-4', 'cli',
                        100, 50, 0, 0, 0, 0.01, 1, old_ts, old_ts,
                        'anthropic', None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            # 4. Fake `revenium` argv-logging shim. Placement is load-bearing:
            #    HOME/.local/bin, prepended onto PATH — anywhere else gets
            #    shadowed by ensure_path's system-path prepends and a real
            #    binary (if present) would run instead.
            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            fake_revenium = os.path.join(bin_dir, 'revenium')
            with open(fake_revenium, 'w') as f:
                f.write(
                    '#!/usr/bin/env bash\n'
                    'case "$1 $2 $3" in\n'
                    '  "config show "* | "config show")\n'
                    '    echo "api_key: mock"; exit 0 ;;\n'
                    '  "jobs --help "* | "jobs --help")\n'
                    '    exit 0 ;;\n'
                    '  "meter completion --help")\n'
                    '    echo "--agentic-job-id --trace-type"; exit 0 ;;\n'
                    '  *)\n'
                    '    exit 0 ;;\n'
                    'esac\n'
                )
            os.chmod(fake_revenium, 0o755)

            log_file = os.path.join(state_dir, 'revenium-metering.log')

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            # 5. Run plugin-status.sh first — fixture has no plugins/ dir and
            #    no config.yaml entry, so this must exit 1 (unregistered).
            status_result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(
                status_result.returncode, 1,
                f'expected exit 1 (unregistered), got {status_result.returncode}:\n'
                f'stdout={status_result.stdout}\nstderr={status_result.stderr}',
            )

            # 6. Run hermes-report.sh — the reporter must read PLUGIN_STATUS_FILE,
            #    see healthy: false, and name the reason in the metering log.
            report_result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )

            self.assertTrue(
                os.path.exists(log_file),
                f'no metering log written; stdout={report_result.stdout}\n'
                f'stderr={report_result.stderr}',
            )
            log_text = Path(log_file).read_text(encoding='utf-8')
            self.assertIn(
                'reason=plugin_unregistered', log_text,
                f'metering log did not name the reason code.\n'
                f'log={log_text}\n'
                f'report stdout={report_result.stdout}\nreport stderr={report_result.stderr}',
            )
            self.assertIn('session=unregistered-sess-1', log_text)


if __name__ == '__main__':
    unittest.main()
