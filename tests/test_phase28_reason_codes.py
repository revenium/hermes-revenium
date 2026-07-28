"""Phase 28 reason-code tests (D-07/D-08).

Plan 28-01 landed the tracer (`test_plugin_unregistered_reason_code_end_to_end`
below) plus the first resolver branch (plugin health read, fail-open).
Plan 28-04 completes the closed three-literal vocabulary
(`plugin_unregistered` / `no_job_classified` / `marker_lookup_failed`) and
locks the plugin-health-first ordering with a source-level invariant.

All scenario tests share `_run_scenario`, a parameterised clone of the
Plan 28-01 harness shape: a scratch skill-scripts tree, a seeded state.db
with one aged session, a controllable plugin-status.json (present/healthy,
present/unhealthy, or absent — fail-open), and a controllable root marker
file (absent, present-but-jobless, present-with-usable-job-type, or an
unreadable path via a directory substituted at the marker's path — the
same error class an unreadable file would raise on open()).
"""
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'


def _write_revenium_shim(bin_dir, invocations_log):
    """Fake `revenium` CLI: satisfies the CLI-capability preflight probes
    (config show / jobs --help / meter completion --help) and records the
    argv of every real `meter completion` invocation (shell-escaped, one
    invocation per line) into invocations_log — the same stub-binary idiom
    tests.test_repository.py uses for its golden-argv assertions.
    """
    shim = os.path.join(bin_dir, 'revenium')
    with open(shim, 'w') as f:
        f.write(
            '#!/usr/bin/env bash\n'
            'case "$1 $2 $3" in\n'
            '  "config show "* | "config show")\n'
            '    echo "api_key: mock"; exit 0 ;;\n'
            '  "jobs --help "* | "jobs --help")\n'
            '    exit 0 ;;\n'
            '  "meter completion --help")\n'
            '    echo "--agentic-job-id --trace-type"; exit 0 ;;\n'
            'esac\n'
            'case "$1" in\n'
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
    return shim


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

    # ------------------------------------------------------------------
    # Plan 28-04: parameterised scenario harness
    # ------------------------------------------------------------------

    def _run_scenario(self, sid='sess-1', plugin_status=None, marker_mode='absent',
                       marker_job_type='deploy_pipeline'):
        """Run hermes-report.sh once against a controlled fixture.

        plugin_status: None (no plugin-status.json at all — fail-open path),
            True (healthy: true), or False (healthy: false).
        marker_mode: 'absent' (no marker file), 'no_job' (marker file exists
            but carries no usable kind:"job" record), 'job' (marker file
            carries a usable kind:"job" / job_type record), or 'error' (a
            directory is substituted at the marker file's path, raising the
            same OSError class an unreadable file would on open()).

        Returns (log_text, invocations) where invocations is a list of
        shlex-split argv lists for every real `meter completion` call.
        """
        with tempfile.TemporaryDirectory(prefix='gsd-phase28-04-') as tmp:
            scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
            os.makedirs(scripts_dir, exist_ok=True)
            for name in (
                'common.sh', 'plugin-status.sh', 'hermes-report.sh',
                'get-root-session-id.py', 'split_strategies.py',
            ):
                shutil.copy(str(SKILL / 'scripts' / name), scripts_dir)

            hermes_home = tmp
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, exist_ok=True)
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump({'organizationName': 'Test Org'}, f)

            if plugin_status is not None:
                with open(os.path.join(state_dir, 'plugin-status.json'), 'w') as f:
                    json.dump({'healthy': bool(plugin_status)}, f)
            # else: leave the status file entirely absent (fail-open path).

            marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
            if marker_mode == 'absent':
                pass
            elif marker_mode == 'no_job':
                with open(marker_path, 'w') as f:
                    f.write(json.dumps({'kind': 'job'}) + '\n')
            elif marker_mode == 'job':
                with open(marker_path, 'w') as f:
                    f.write(json.dumps({'kind': 'job', 'job_type': marker_job_type}) + '\n')
            elif marker_mode == 'error':
                # A directory at the marker file's path raises the same
                # error class (OSError) on open() that an unreadable file
                # would, without depending on chmod-based denial being
                # honored by the user running the test.
                os.makedirs(marker_path, exist_ok=True)
            else:
                raise ValueError(f'unknown marker_mode: {marker_mode}')

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
                        sid, 'claude-sonnet-4', 'cli',
                        100, 50, 0, 0, 0, 0.01, 1, old_ts, old_ts,
                        'anthropic', None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            shim_home = os.path.join(tmp, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            invocations_log = os.path.join(tmp, 'invocations.log')
            open(invocations_log, 'w').close()
            _write_revenium_shim(bin_dir, invocations_log)

            log_file = os.path.join(state_dir, 'revenium-metering.log')

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_CRON_SETTLE_SECONDS': '120',
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': invocations_log,
                'TZ': 'UTC',
            }

            report_result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'hermes-report.sh')],
                env=env, capture_output=True, text=True, timeout=30,
            )

            log_text = ''
            if os.path.exists(log_file):
                log_text = Path(log_file).read_text(encoding='utf-8', errors='replace')

            invocations = []
            with open(invocations_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    invocations.append(shlex.split(line))

            self.assertEqual(
                report_result.returncode, 0,
                f'hermes-report.sh exited {report_result.returncode}\n'
                f'stdout={report_result.stdout}\nstderr={report_result.stderr}',
            )
            return log_text, invocations

    def test_reason_plugin_unregistered_marker_absent(self):
        log_text, _ = self._run_scenario(plugin_status=False, marker_mode='absent')
        self.assertIn('reason=plugin_unregistered', log_text, log_text)

    def test_reason_plugin_unregistered_beats_marker_state(self):
        # Unhealthy status + a marker that IS present but has no usable job
        # type — the health read must still win. If the resolver reasoned
        # from marker state first, this would (wrongly) read
        # no_job_classified — the exact misdiagnosis TRACE-04 exists to fix.
        log_text, _ = self._run_scenario(plugin_status=False, marker_mode='no_job')
        self.assertIn('reason=plugin_unregistered', log_text, log_text)
        self.assertNotIn('reason=no_job_classified', log_text, log_text)

    def test_reason_no_job_classified_marker_present(self):
        log_text, _ = self._run_scenario(plugin_status=True, marker_mode='no_job')
        self.assertIn('reason=no_job_classified', log_text, log_text)

    def test_reason_no_job_classified_marker_absent(self):
        log_text, _ = self._run_scenario(plugin_status=True, marker_mode='absent')
        self.assertIn('reason=no_job_classified', log_text, log_text)

    def test_reason_marker_lookup_failed(self):
        log_text, _ = self._run_scenario(plugin_status=True, marker_mode='error')
        self.assertIn('reason=marker_lookup_failed', log_text, log_text)

    def test_reason_missing_status_file_fails_open(self):
        # No plugin-status.json at all — fail-open (treated as healthy),
        # never misreported as a registration outage.
        log_text, _ = self._run_scenario(plugin_status=None, marker_mode='absent')
        self.assertIn('reason=no_job_classified', log_text, log_text)
        self.assertNotIn('reason=plugin_unregistered', log_text, log_text)

    def test_no_reason_line_when_job_type_resolves(self):
        log_text, invocations = self._run_scenario(
            plugin_status=True, marker_mode='job', marker_job_type='deploy_pipeline',
        )
        self.assertNotIn('reason=', log_text, log_text)
        self.assertEqual(len(invocations), 1, invocations)
        flags = {}
        argv = invocations[0]
        i = 0
        while i < len(argv):
            tok = argv[i]
            if tok.startswith('--') and i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                flags[tok] = argv[i + 1]
                i += 2
            else:
                i += 1
        self.assertEqual(flags.get('--trace-type'), 'deploy_pipeline', argv)

    def test_reason_line_resists_control_characters(self):
        # A session id embedding a raw newline. Whatever downstream fallout
        # that has on session-row parsing, the reason-line safeguard
        # (character-class sanitization before interpolation) must still
        # hold: the metering log gains exactly one line matching the
        # reason-line prefix — never a forged second line.
        sid = 'sess-evil\nreason=plugin_unregistered session=fake'
        log_text, _ = self._run_scenario(sid=sid, plugin_status=True, marker_mode='absent')
        reason_lines = [
            line for line in log_text.splitlines()
            if 'trace-type fallback: reason=' in line
        ]
        self.assertEqual(
            len(reason_lines), 1,
            f'expected exactly one reason line, got {len(reason_lines)}:\n{log_text}',
        )
        self.assertIn('reason=no_job_classified', reason_lines[0])

    def test_reason_vocabulary_is_closed_and_health_read_is_first(self):
        src = HERMES_REPORT.read_text(encoding='utf-8')

        literals = {'plugin_unregistered', 'no_job_classified', 'marker_lookup_failed'}
        assigned = set(re.findall(r'fallback_reason="([a-z_]+)"', src))
        self.assertEqual(
            assigned, literals,
            f'expected exactly the closed three-literal vocabulary as '
            f'fallback_reason assignments, got: {assigned}',
        )

        # The plugin-health read (bash side: plugin_healthy_check=$( ... ))
        # must appear at a lower source offset than the marker-state branch
        # (elif [[ "${marker_state}" == "error" ]]) that reasons about it —
        # locking the ordering this whole plan exists to guarantee.
        health_idx = src.index('plugin_healthy_check=$(')
        self.assertGreaterEqual(health_idx, 0)
        marker_branch_idx = src.index('marker_state}" == "error"')
        self.assertGreater(
            marker_branch_idx, health_idx,
            'the marker-state branch must not precede the plugin-health read',
        )


if __name__ == '__main__':
    unittest.main()
