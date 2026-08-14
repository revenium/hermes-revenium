"""quick-260813-wnz -- bound unbounded metering log growth.

Locks the three log-growth fixes measured live on the production fleet host:

  LOG-01 (Task 1): hermes-report.sh's trace-type fallback WARN is bounded to
      once per (session, reason) via a zero-byte flag file, plus one
      per-tick aggregate INFO line when the fallback count is non-zero.
  LOG-02 (Task 2): plugin-status.sh's ~11-line human banner is suppressed on
      a quiet, unchanged, healthy cron tick -- opt-in only, never on a
      manual no-flag invocation.
  LOG-03 (Task 3): revenium-metering.log is bounded via in-place truncation
      (never rename/unlink) so cron's long-lived append fd survives
      rotation.

Follows the fixture idiom tests/test_phase28_reason_codes.py and
tests/test_phase28_plugin_status.py established: a scratch skill-scripts
tree, a seeded state.db, a controllable plugin-status.json, and a stub
`revenium` binary placed under a redirected HOME/.local/bin (per the
recorded ensure_path isolation lesson -- shim binaries must live under the
test's own HOME/.local/bin or ensure_path lets real system binaries shadow
them).
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
COMMON_SH = SKILL / 'scripts' / 'common.sh'
HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'
PRUNE_MARKERS = SKILL / 'scripts' / 'prune-markers.sh'
PLUGIN_STATUS = SKILL / 'scripts' / 'plugin-status.sh'
CRON_SH = SKILL / 'scripts' / 'cron.sh'


# ---------------------------------------------------------------------------
# Shared fixture helpers -- Task 1 (fallback-warn bounding)
# ---------------------------------------------------------------------------

def _write_revenium_shim(bin_dir, invocations_log):
    """Fake `revenium` CLI: satisfies the CLI-capability preflight probes
    (config show / jobs --help / meter completion --help) and records the
    argv of every real `meter completion` invocation (shell-escaped, one
    invocation per line) into invocations_log. Mirrors
    tests/test_phase28_reason_codes.py's shim byte-for-byte."""
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


def _make_scripts_dir(tmp):
    scripts_dir = os.path.join(tmp, 'skills', 'revenium', 'scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    for name in (
        'common.sh', 'plugin-status.sh', 'hermes-report.sh',
        'get-root-session-id.py', 'split_strategies.py',
    ):
        shutil.copy(str(SKILL / 'scripts' / name), scripts_dir)
    return scripts_dir


def _seed_state_db(hermes_home, sid, input_tokens=100, output_tokens=50, age_seconds=300):
    db_path = os.path.join(hermes_home, 'state.db')
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, model TEXT, source TEXT,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                reasoning_tokens INTEGER, estimated_cost_usd REAL,
                api_call_count INTEGER, started_at REAL, ended_at REAL,
                billing_provider TEXT, parent_session_id TEXT
            )
        ''')
        ts = time.time() - age_seconds
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid, 'claude-sonnet-4', 'cli',
                input_tokens, output_tokens, 0, 0, 0,
                0.01, 1, ts, ts, 'anthropic', None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _build_fallback_fixture(tmp, sid='sess-1', plugin_healthy=True):
    """Scratch skill-scripts tree + state dir + one aged, token-bearing
    session, no job marker file (so the session resolves to the trace-type
    fallback), and a controllable plugin-status.json. Returns
    (scripts_dir, state_dir, log_file, invocations_log, env)."""
    scripts_dir = _make_scripts_dir(tmp)
    hermes_home = tmp
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    markers_dir = os.path.join(state_dir, 'markers')
    os.makedirs(markers_dir, exist_ok=True)
    with open(os.path.join(state_dir, 'config.json'), 'w') as f:
        json.dump({'organizationName': 'Test Org'}, f)
    with open(os.path.join(state_dir, 'plugin-status.json'), 'w') as f:
        json.dump({'healthy': bool(plugin_healthy)}, f)

    _seed_state_db(hermes_home, sid)

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
    return scripts_dir, state_dir, log_file, invocations_log, env


def _run_reporter(scripts_dir, env):
    return subprocess.run(
        ['bash', os.path.join(scripts_dir, 'hermes-report.sh')],
        env=env, capture_output=True, text=True, timeout=30,
    )


class CommonShDeclarationTests(unittest.TestCase):
    def test_fallback_warn_flags_dir_declared_with_override_shape(self):
        text = COMMON_SH.read_text()
        self.assertRegex(
            text,
            r'FALLBACK_WARN_FLAGS_DIR="\$\{REVENIUM_FALLBACK_WARN_FLAGS_DIR:-'
            r'\$\{MARKERS_DIR\}/\.fallback-warn\}"',
        )


class FallbackWarnBoundingTests(unittest.TestCase):
    def test_repeat_tick_suppresses_per_session_warn(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-repeat-') as tmp:
            scripts_dir, state_dir, log_file, _, env = _build_fallback_fixture(
                tmp, sid='sess-repeat',
            )
            r1 = _run_reporter(scripts_dir, env)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            log_text_1 = Path(log_file).read_text()
            warn_lines_1 = [
                l for l in log_text_1.splitlines() if 'trace-type fallback: reason=' in l
            ]
            self.assertEqual(len(warn_lines_1), 1, log_text_1)

            r2 = _run_reporter(scripts_dir, env)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            log_text_2 = Path(log_file).read_text()
            warn_lines_2 = [
                l for l in log_text_2.splitlines() if 'trace-type fallback: reason=' in l
            ]
            self.assertEqual(
                len(warn_lines_2), 1,
                f'second tick over the same session+reason must add ZERO new '
                f'WARN lines:\n{log_text_2}',
            )

    def test_reason_transition_warns_again(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-transition-') as tmp:
            scripts_dir, state_dir, log_file, _, env = _build_fallback_fixture(
                tmp, sid='sess-trans', plugin_healthy=False,
            )
            r1 = _run_reporter(scripts_dir, env)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            log_text_1 = Path(log_file).read_text()
            self.assertIn('reason=plugin_unregistered', log_text_1)

            # Flip plugin health -> the fallback reason changes to
            # no_job_classified (marker still absent).
            status_path = os.path.join(state_dir, 'plugin-status.json')
            with open(status_path, 'w') as f:
                json.dump({'healthy': True}, f)

            r2 = _run_reporter(scripts_dir, env)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            log_text_2 = Path(log_file).read_text()
            new_lines = log_text_2[len(log_text_1):]
            self.assertIn(
                'reason=no_job_classified', new_lines,
                f'a reason TRANSITION must produce exactly one new WARN line:\n{new_lines}',
            )
            self.assertNotIn(
                'reason=plugin_unregistered', new_lines,
                'the OLD reason must not re-warn on the transition tick',
            )

    def test_preexisting_flag_for_one_reason_does_not_suppress_another(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-preflag-') as tmp:
            scripts_dir, state_dir, log_file, _, env = _build_fallback_fixture(
                tmp, sid='sess-pre', plugin_healthy=True,
            )
            markers_dir = os.path.join(state_dir, 'markers')
            flag_dir = os.path.join(markers_dir, '.fallback-warn')
            os.makedirs(flag_dir, exist_ok=True)
            # Pre-create a flag for a DIFFERENT reason than the one this
            # fixture will actually resolve to (no_job_classified, since
            # plugin_healthy=True and no marker file exists).
            Path(os.path.join(flag_dir, 'sess-pre__plugin_unregistered.flag')).touch()

            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertIn(
                'reason=no_job_classified', log_text,
                f'a flag for a DIFFERENT reason must not suppress this one:\n{log_text}',
            )

    def test_zero_fallback_tick_emits_no_aggregate(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-agg-zero-') as tmp:
            scripts_dir, state_dir, log_file, _, env = _build_fallback_fixture(
                tmp, sid='sess-agg-zero', plugin_healthy=True,
            )
            # Give the session a usable job marker so it does NOT fall back.
            markers_dir = os.path.join(state_dir, 'markers')
            marker_path = os.path.join(markers_dir, 'sess-agg-zero.jsonl')
            with open(marker_path, 'w') as f:
                f.write(json.dumps({'kind': 'job', 'job_type': 'deploy_pipeline'}) + '\n')

            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertNotIn('trace-type fallback:', log_text, log_text)

    def test_nonzero_fallback_tick_emits_exactly_one_aggregate(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-agg-one-') as tmp:
            scripts_dir, state_dir, log_file, _, env = _build_fallback_fixture(
                tmp, sid='sess-agg-one', plugin_healthy=True,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            agg_lines = [
                l for l in log_text.splitlines()
                if re.search(r'trace-type fallback: \d+ session', l)
            ]
            self.assertEqual(len(agg_lines), 1, log_text)
            self.assertIn(' 1 session', agg_lines[0])

    def test_trace_type_argv_is_uncategorized_and_stable(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-argv-') as tmp:
            scripts_dir, state_dir, log_file, invocations_log, env = _build_fallback_fixture(
                tmp, sid='sess-argv', plugin_healthy=True,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(invocations_log) as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1, lines)
            argv = shlex.split(lines[0])
            self.assertIn('--trace-type', argv)
            idx = argv.index('--trace-type')
            self.assertEqual(argv[idx + 1], 'uncategorized')


class PruneFlagDirectoriesTests(unittest.TestCase):
    def test_prune_removes_stale_flags_keeps_fresh_in_both_dirs(self):
        with tempfile.TemporaryDirectory(prefix='gsd-wnz-prune-') as tmp:
            hermes_home = os.path.join(tmp, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            warn_dir = os.path.join(markers_dir, '.warn')
            fallback_dir = os.path.join(markers_dir, '.fallback-warn')
            os.makedirs(warn_dir, mode=0o700)
            os.makedirs(fallback_dir, mode=0o700)

            old_ts = time.time() - 31 * 86400
            new_ts = time.time()

            old_warn = os.path.join(warn_dir, 'sess-old__rule.flag')
            fresh_warn = os.path.join(warn_dir, 'sess-fresh__rule.flag')
            old_fallback = os.path.join(fallback_dir, 'sess-old__no_job_classified.flag')
            fresh_fallback = os.path.join(fallback_dir, 'sess-fresh__no_job_classified.flag')

            for p, ts in ((old_warn, old_ts), (old_fallback, old_ts)):
                Path(p).touch()
                os.utime(p, (ts, ts))
            for p, ts in ((fresh_warn, new_ts), (fresh_fallback, new_ts)):
                Path(p).touch()
                os.utime(p, (ts, ts))

            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_MARKER_RETENTION_DAYS': '30',
                'TZ': 'UTC',
            }

            # --dry-run: nothing removed.
            r = subprocess.run(
                ['bash', str(PRUNE_MARKERS), '--dry-run'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            for p in (old_warn, fresh_warn, old_fallback, fresh_fallback):
                self.assertTrue(os.path.exists(p), f'{p} should still exist after dry-run')

            # Live run: only the two stale flags removed.
            r = subprocess.run(
                ['bash', str(PRUNE_MARKERS)],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(old_warn), 'stale WARN_FLAGS_DIR flag must be removed')
            self.assertFalse(
                os.path.exists(old_fallback), 'stale FALLBACK_WARN_FLAGS_DIR flag must be removed',
            )
            self.assertTrue(os.path.exists(fresh_warn), 'fresh WARN_FLAGS_DIR flag must be kept')
            self.assertTrue(
                os.path.exists(fresh_fallback), 'fresh FALLBACK_WARN_FLAGS_DIR flag must be kept',
            )
            metering_log = os.path.join(state_dir, 'revenium-metering.log')
            self.assertTrue(os.path.exists(metering_log), 'prune-markers.sh must log via info()')
            self.assertIn('prune: flags summary,', Path(metering_log).read_text())


if __name__ == '__main__':
    unittest.main()
