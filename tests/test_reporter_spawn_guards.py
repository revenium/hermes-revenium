"""quick-260814-e7c -- cut hermes-report.sh's per-session python3 spawn cost.

Locks the bash-guard equivalent of four heredocs (H2, H3, H4, H5) that already
test a file-existence predicate as their own first action:

  H5 (Task 1): the WR-02 job-marker scan is guarded by `-f` on the session
      marker file, mirroring `marker_path.is_file()`. This is the 84%-of-
      sessions case on the live fleet host and the load-bearing WR-02
      regression guard: a token-stable session (already in the HERMES ledger)
      WITH a job marker must still reach `revenium jobs create`.
  H2 (Task 2): the trace-type / marker-state heredoc is guarded by `-e` on
      the root marker file, mirroring `marker_path.exists()`.
  H3 (Task 2): the plugin-health heredoc is guarded by `-s` on
      PLUGIN_STATUS_FILE, mirroring the heredoc's own fail-open-on-any-
      exception body (missing / empty-string / zero-byte all raise and
      print 'true').
  H4 (Task 2): the root agentic-job-id heredoc is guarded by `-e` on the
      root marker file (subagent sessions only), mirroring `exists()`.

`-f` (`is_file()`) and `-e` (`exists()`) are NOT interchangeable: `exists()`
is True for a directory, whose subsequent `open()` raises OSError -- H2 must
still spawn python3 for that shape and resolve `marker_lookup_failed`, not
silently misreport `no_job_classified`. The directory-shaped-marker tests
below are what catch a `-f`/`-e` mix-up.

Follows the fixture idiom established by tests/test_bounded_logging.py and
tests/test_phase28_reason_codes.py: a scratch skill-scripts tree, a seeded
state.db, a controllable plugin-status.json, and a stub `revenium` binary
under a redirected HOME/.local/bin (ensure_path prepends `${HOME}/.local/bin`
LAST, so it lands FIRST in PATH and wins over any real system binary -- a
stub anywhere else is shadowed).
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_bounded_logging import (
    _make_scripts_dir,
    _seed_state_db,
    _write_revenium_shim,
)

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
HERMES_REPORT = SKILL / 'scripts' / 'hermes-report.sh'

# Captured once at import time so the shim can exec the SAME interpreter
# running this test suite, by absolute path -- no PATH lookup inside the shim.
REAL_PYTHON3 = sys.executable

# Measured spawn ceiling for a no-marker, first-tick session against THIS
# committed script (macOS, Python 3.x stdlib subprocess). Task 1 alone
# measured 14 (H5 guard only); Task 2 lowered it to 13 (H2/H3/H4 landed);
# Task 3's root-markers-dir memoization for top-level sessions (PERF-02)
# lowered it once more, to 12. Locking a ceiling (rather than only the
# relational property below) catches a future edit that adds an
# unconditional spawn to the hot path without also lowering this constant.
#
# Phase 32 Plan 03 (C-11/D-13) raises it back to 13: resolve_switch_setting
# (common.sh) reads config.json's legacyCompletions key via ONE python3
# spawn at STARTUP -- once per run, not once per session and not inside the
# per-session loop this file's guards otherwise police -- whenever
# REVENIUM_LEGACY_COMPLETIONS is unset AND config.json exists (this
# fixture's config.json always exists, for organizationName). A fixed
# per-run cost is architecturally different from the per-session/per-record
# hot-path cost quick-260814-e7c cut; the relational property below (fewer
# spawns than a marker-present session) is what actually polices runaway
# per-session growth.
#
# Phase 44 Plan 04 (EGV-17/D-15) raises it once more, to 14: the end-of-run
# summary block gained ONE python3 heredoc that calls partition_by_attribution
# over the tick's accumulated attribution_rows and prints the classified/
# unclassified/unallocated reconciliation line. Same shape as the Phase 32
# Plan 03 exemption above -- it runs ONCE PER TICK after the session loop
# closes, not once per session, so it does not scale with fleet size. It is
# also not avoidable in bash: Decimal-exact cost summation across an
# unbounded row count is exactly the arithmetic split_strategies.py already
# owns, and duplicating it in bash would defeat the single-source-of-truth
# point of that module. A markerless single-session tick (this test's "no
# marker" fixture) still populates attribution_rows (unclassified +
# possibly unallocated rows), so the extra spawn lands on BOTH sides of the
# relational comparison below and the strictly-fewer property still holds.
NO_MARKER_SPAWN_CEILING = 14


def _write_python_spawn_shim(bin_dir, spawn_log_path):
    """Fake `python3`: satisfies the reporter's `command -v python3` preflight,
    appends one line to $PY_SPAWN_LOG per invocation, then execs the REAL
    interpreter (by absolute path, captured at import time) with argv passed
    through unchanged -- transparent to every real heredoc in the reporter."""
    shim = os.path.join(bin_dir, 'python3')
    with open(shim, 'w') as f:
        f.write(
            '#!/bin/sh\n'
            'echo x >> "$PY_SPAWN_LOG"\n'
            f'exec {shlex.quote(REAL_PYTHON3)} "$@"\n'
        )
    os.chmod(shim, 0o755)
    return shim


def _build_spawn_fixture(tmp, sid='sess-1', marker_mode='absent',
                          marker_job_id='job-abc', plugin_healthy=True):
    """Scratch skill-scripts tree + state dir + one aged, token-bearing
    session, a controllable root marker (absent / job / directory-shaped),
    and both the `revenium` argv-recording shim and the `python3` spawn-
    counting shim under the same redirected HOME/.local/bin.

    Returns (scripts_dir, state_dir, log_file, ledger_file,
    jobs_ledger_file, invocations_log, spawn_log, env).
    """
    scripts_dir = _make_scripts_dir(tmp)
    hermes_home = tmp
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    markers_dir = os.path.join(state_dir, 'markers')
    os.makedirs(markers_dir, exist_ok=True)
    with open(os.path.join(state_dir, 'config.json'), 'w') as f:
        json.dump({'organizationName': 'Test Org'}, f)
    with open(os.path.join(state_dir, 'plugin-status.json'), 'w') as f:
        json.dump({'healthy': bool(plugin_healthy)}, f)

    marker_path = os.path.join(markers_dir, f'{sid}.jsonl')
    if marker_mode == 'absent':
        pass
    elif marker_mode == 'job':
        with open(marker_path, 'w') as f:
            f.write(json.dumps({
                'kind': 'job',
                'agentic_job_id': marker_job_id,
                'job_type': 'deploy_pipeline',
                'job_name': 'deploy',
                'status': 'SUCCESS',
            }) + '\n')
    elif marker_mode == 'no_job':
        with open(marker_path, 'w') as f:
            f.write(json.dumps({'kind': 'job'}) + '\n')
    elif marker_mode == 'directory':
        os.makedirs(marker_path, exist_ok=True)
    else:
        raise ValueError(f'unknown marker_mode: {marker_mode}')

    _seed_state_db(hermes_home, sid)

    shim_home = os.path.join(tmp, 'home')
    bin_dir = os.path.join(shim_home, '.local', 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    invocations_log = os.path.join(tmp, 'invocations.log')
    open(invocations_log, 'w').close()
    _write_revenium_shim(bin_dir, invocations_log)

    spawn_log = os.path.join(tmp, 'py-spawns.log')
    open(spawn_log, 'w').close()
    _write_python_spawn_shim(bin_dir, spawn_log)

    log_file = os.path.join(state_dir, 'revenium-metering.log')
    ledger_file = os.path.join(state_dir, 'revenium-hermes.ledger')
    jobs_ledger_file = os.path.join(state_dir, 'revenium-jobs.ledger')

    env = {
        **os.environ,
        'HOME': shim_home,
        'HERMES_HOME': hermes_home,
        'REVENIUM_STATE_DIR': state_dir,
        'REVENIUM_MARKERS_DIR': markers_dir,
        'REVENIUM_CRON_SETTLE_SECONDS': '120',
        'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
        'INVOCATIONS_LOG': invocations_log,
        'PY_SPAWN_LOG': spawn_log,
        'TZ': 'UTC',
    }
    return (
        scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
        invocations_log, spawn_log, env,
    )


def _run_reporter(scripts_dir, env):
    return subprocess.run(
        ['bash', os.path.join(scripts_dir, 'hermes-report.sh')],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _seed_ledger_token_stable(ledger_file, sid, total_tokens=150):
    """Write a HERMES ledger row for `sid` whose token total already equals
    the seeded session's total (100 input + 50 output), so the token
    pre-filter below the WR-02 scan would `continue` this session -- the
    exact D-08 arc-close shape the WR-02 scan exists to reach past."""
    with open(ledger_file, 'w') as f:
        f.write(f'HERMES:{sid}:{total_tokens}:{time.time():.3f}\n')


def _spawn_count(spawn_log):
    with open(spawn_log) as f:
        return len([l for l in f.read().splitlines() if l.strip()])


class WR02JobMarkerScanGuardTests(unittest.TestCase):
    """Task 1 -- H5 guard (`-f` mirroring `is_file()`)."""

    def test_no_marker_token_stable_session_is_a_noop(self):
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h5-nomarker-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = _build_spawn_fixture(
                tmp, sid='sess-h5-a', marker_mode='absent',
            )
            _seed_ledger_token_stable(ledger_file, 'sess-h5-a')
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(
                Path(invocations_log).read_text().strip(), '',
                'a token-stable, no-marker session must not re-meter',
            )
            ledger_text = Path(ledger_file).read_text()
            self.assertEqual(
                ledger_text.count('HERMES:sess-h5-a:'), 1,
                f'ledger must gain no new row: {ledger_text}',
            )
            jobs_text = (
                Path(jobs_ledger_file).read_text()
                if os.path.exists(jobs_ledger_file) else ''
            )
            self.assertNotIn('JOB:', jobs_text, jobs_text)

    def test_wr02_token_stable_session_with_job_marker_still_creates_job(self):
        """THE regression guard against the forbidden approach (see PLAN.md's
        <forbidden_approach>): no guard in this plan may key off token
        totals, ledger presence, or ended_at. A token-stable session (its
        total already recorded in the HERMES ledger) that carries a job
        marker must still reach `revenium jobs create` -- Phase 9's WR-02
        fix, which this guard sits directly beneath."""
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h5-wr02-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = _build_spawn_fixture(
                tmp, sid='sess-h5-b', marker_mode='job', marker_job_id='job-wr02',
            )
            _seed_ledger_token_stable(ledger_file, 'sess-h5-b')
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(
                os.path.exists(jobs_ledger_file),
                'jobs ledger must exist -- the WR-02 scan must have run',
            )
            jobs_text = Path(jobs_ledger_file).read_text()
            self.assertIn(
                'JOB:job-wr02:created:', jobs_text,
                f'a token-stable session with a job marker must still reach '
                f'jobs create: {jobs_text}',
            )
            # WR-02's own token-stability contract: the session itself must
            # NOT have been re-metered just because it also has a job.
            self.assertEqual(
                Path(invocations_log).read_text().strip(), '',
                'token-stable session must not re-meter even though its '
                'job marker was processed',
            )

    def test_directory_shaped_session_marker_creates_no_job(self):
        """`-f` (bash) mirrors `is_file()` (Python), which is False for a
        directory -- proving `-f`, not `-e`, was used for H5."""
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h5-dir-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = _build_spawn_fixture(
                tmp, sid='sess-h5-c', marker_mode='directory',
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            jobs_text = (
                Path(jobs_ledger_file).read_text()
                if os.path.exists(jobs_ledger_file) else ''
            )
            self.assertNotIn('JOB:', jobs_text, jobs_text)


class TraceTypeAndPluginHealthGuardTests(unittest.TestCase):
    """Task 2 -- H2 (`-e`), H3 (`-s`), H4 (`-e`, subagent-only) guards."""

    def test_no_root_marker_resolves_no_job_classified(self):
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h2-absent-') as tmp:
            (scripts_dir, state_dir, log_file, *_rest, env) = _build_spawn_fixture(
                tmp, sid='sess-h2-absent', marker_mode='absent', plugin_healthy=True,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertIn('reason=no_job_classified', log_text, log_text)

    def test_directory_shaped_root_marker_resolves_marker_lookup_failed(self):
        """`-e` (bash) mirrors `exists()` (Python), which is True for a
        directory -- so this case must still spawn python3 and resolve to
        the distinct `marker_lookup_failed` reason, NOT silently fall
        through to `no_job_classified` (which a wrong `-f` guard would
        produce by treating the directory as absent)."""
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h2-dir-') as tmp:
            (scripts_dir, state_dir, log_file, *_rest, env) = _build_spawn_fixture(
                tmp, sid='sess-h2-dir', marker_mode='directory', plugin_healthy=True,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertIn('reason=marker_lookup_failed', log_text, log_text)
            self.assertNotIn('reason=no_job_classified', log_text, log_text)

    def test_job_marker_present_ships_trace_type_no_reason_line(self):
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h2-job-') as tmp:
            (scripts_dir, state_dir, log_file, ledger_file, jobs_ledger_file,
             invocations_log, spawn_log, env) = _build_spawn_fixture(
                tmp, sid='sess-h2-job', marker_mode='job', plugin_healthy=True,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertNotIn('reason=', log_text, log_text)
            argv = shlex.split(Path(invocations_log).read_text().strip())
            self.assertIn('--trace-type', argv)
            self.assertEqual(argv[argv.index('--trace-type') + 1], 'deploy_pipeline')

    def test_zero_byte_plugin_status_fails_open_to_no_job_classified(self):
        """`-s` (bash) mirrors the heredoc's own fail-open-on-exception body:
        a zero-byte plugin-status.json must resolve exactly like a healthy
        read, NOT like an unregistered plugin. A `-f` guard would also pass
        (a zero-byte file still exists as a regular file), but `-s` is the
        predicate that additionally matches the heredoc's actual `except
        Exception` semantics for the zero-byte case specifically."""
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h3-zerobyte-') as tmp:
            (scripts_dir, state_dir, log_file, *_rest, env) = _build_spawn_fixture(
                tmp, sid='sess-h3-zero', marker_mode='absent', plugin_healthy=True,
            )
            status_path = os.path.join(state_dir, 'plugin-status.json')
            open(status_path, 'w').close()  # truncate to zero bytes
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertIn('reason=no_job_classified', log_text, log_text)
            self.assertNotIn('reason=plugin_unregistered', log_text, log_text)

    def test_unhealthy_plugin_status_wins_over_marker_state(self):
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-h3-unhealthy-') as tmp:
            (scripts_dir, state_dir, log_file, *_rest, env) = _build_spawn_fixture(
                tmp, sid='sess-h3-unhealthy', marker_mode='absent', plugin_healthy=False,
            )
            r = _run_reporter(scripts_dir, env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            log_text = Path(log_file).read_text()
            self.assertIn('reason=plugin_unregistered', log_text, log_text)


class SpawnCeilingTests(unittest.TestCase):
    """Measured spawn-count relational property + locked ceiling."""

    def test_no_marker_session_spawns_strictly_fewer_than_marker_present(self):
        with tempfile.TemporaryDirectory(prefix='gsd-e7c-spawn-nomarker-') as tmp_a, \
             tempfile.TemporaryDirectory(prefix='gsd-e7c-spawn-marker-') as tmp_b:
            (scripts_dir_a, _sd_a, _lf_a, _ledger_a, _jl_a, _inv_a, spawn_log_a,
             env_a) = _build_spawn_fixture(tmp_a, sid='sess-spawn-a', marker_mode='absent')
            (scripts_dir_b, _sd_b, _lf_b, _ledger_b, _jl_b, _inv_b, spawn_log_b,
             env_b) = _build_spawn_fixture(tmp_b, sid='sess-spawn-b', marker_mode='job')

            r_a = _run_reporter(scripts_dir_a, env_a)
            self.assertEqual(r_a.returncode, 0, r_a.stdout + r_a.stderr)
            r_b = _run_reporter(scripts_dir_b, env_b)
            self.assertEqual(r_b.returncode, 0, r_b.stdout + r_b.stderr)

            spawn_count_a = _spawn_count(spawn_log_a)
            spawn_count_b = _spawn_count(spawn_log_b)

            self.assertLess(
                spawn_count_a, spawn_count_b,
                f'no-marker session ({spawn_count_a} spawns) must spawn '
                f'strictly fewer python3 processes than the marker-present '
                f'session ({spawn_count_b} spawns)',
            )
            self.assertLessEqual(
                spawn_count_a, NO_MARKER_SPAWN_CEILING,
                f'no-marker session spawned {spawn_count_a} python3 '
                f'processes, exceeding the measured ceiling of '
                f'{NO_MARKER_SPAWN_CEILING} -- either a new unconditional '
                f'spawn was added to the hot path, or the ceiling needs '
                f're-measuring downward after a further guard landed',
            )


class GuardPermanenceTests(unittest.TestCase):
    """Task 3 Part B -- each guard literal must precede, and stay near, the
    heredoc anchor it guards, using the same `src.index(...)` ordering idiom
    as tests/test_phase28_reason_codes.py's health-read-ordering assertion.

    Guard -> mirrored Python predicate (documented here so a future editor
    reading a failure learns why `-f` vs `-e` vs `-s` matters):
      H5: `-f` mirrors `marker_path.is_file()` (WR-02 job-marker scan).
      H2: `-e` mirrors `marker_path.exists()` (trace-type / marker-state).
      H3: `-s` mirrors the plugin-health heredoc's fail-open-on-exception
          body (covers missing / empty-string / zero-byte, unlike `-f`).
      H4: `-e` mirrors `marker_path.exists()` (root agentic-job id,
          subagent-only).
    """

    GUARD_PAIRS = (
        (
            'H5',
            'JOBS_CLI_CAPABLE}" == "true" && -f "${session_markers_dir}/${sid}.jsonl"',
            "MARKERS_DIR=\"${session_markers_dir}\" \\",
            4000,
        ),
        (
            'H2',
            'if [[ -e "${root_markers_dir}/${root_sid}.jsonl" ]]; then',
            "ROOT_SID=\"${root_sid}\" MARKERS_DIR=\"${root_markers_dir}\" python3 - <<'PY' 2>/dev/null\nimport json, os\nfrom pathlib import Path\nroot_sid = os.environ.get('ROOT_SID', '')\nmarkers_dir = os.environ.get('MARKERS_DIR', '')\nlatest_type",
            2000,
        ),
        (
            'H3',
            'if [[ -s "${PLUGIN_STATUS_FILE}" ]]; then',
            'plugin_healthy_check=$(',
            1000,
        ),
        (
            'H4',
            'root_sid}" != "${sid}" && -e "${root_markers_dir}/${root_sid}.jsonl" ]]; then',
            "ROOT_SID=\"${root_sid}\" MARKERS_DIR=\"${root_markers_dir}\" python3 - <<'PY' 2>/dev/null || true\nimport json, os\nfrom pathlib import Path\nroot_sid = os.environ.get('ROOT_SID', '')\nmarkers_dir = os.environ.get('MARKERS_DIR', '')\nif not root_sid or not markers_dir:",
            1500,
        ),
    )

    def test_each_guard_precedes_and_is_near_its_heredoc_anchor(self):
        src = HERMES_REPORT.read_text(encoding='utf-8')
        for name, guard_literal, heredoc_anchor, max_window in self.GUARD_PAIRS:
            guard_idx = src.index(guard_literal)
            anchor_idx = src.index(heredoc_anchor)
            self.assertLess(
                guard_idx, anchor_idx,
                f'{name}: guard literal must precede its heredoc anchor',
            )
            self.assertLess(
                anchor_idx - guard_idx, max_window,
                f'{name}: guard literal is too far from its heredoc anchor '
                f'({anchor_idx - guard_idx} chars) -- likely guarding the '
                f'wrong heredoc',
            )

    def test_h1_already_guarded_heredoc_untouched(self):
        """H1 (root_agent_output) was already guarded before this plan
        (Phase 29) -- this plan must not touch it."""
        src = HERMES_REPORT.read_text(encoding='utf-8')
        self.assertIn(
            'if [[ -f "${root_markers_dir}/${root_sid}.jsonl" ]]; then',
            src,
        )

    def test_root_markers_dir_memoized_for_top_level_sessions(self):
        """Task 3 Part A (PERF-02, severable) -- for a top-level session
        (root_sid == sid), root_markers_dir must be assigned directly from
        session_markers_dir rather than re-resolved via a second
        resolve_markers_dir call. Both original call sites must remain
        present in the file (T-28-34's exact-count invariant), plus the one
        Phase 38 (ROI-10/T-38-03) legitimately adds: the post-loop outcome
        stage re-reads a session's marker for its assessment, using the same
        helper the in-loop path already uses, so a multiplexed gateway's
        per-profile marker home is resolved consistently on both paths."""
        src = HERMES_REPORT.read_text(encoding='utf-8')
        self.assertIn('root_markers_dir="${session_markers_dir}"', src)
        # Count INVOCATIONS, not bare mentions: this file's conventions
        # encourage comments that name the helper they describe (Phase 42
        # Plan 05 added one such comment), and a prose mention is not a
        # call site. Counting '$(resolve_markers_dir ' measures the
        # invariant this test's own docstring states, and still fails if a
        # call site is added or removed.
        self.assertEqual(
            src.count('$(resolve_markers_dir '), 3,
            'exactly three resolve_markers_dir call sites must remain '
            '(T-28-34\'s original two, plus Phase 38\'s outcome-stage read)',
        )


if __name__ == '__main__':
    unittest.main()
