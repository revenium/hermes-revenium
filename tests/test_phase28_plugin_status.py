"""Phase 28 Plan 01 Task 2 — locks plugin-status.sh's exit-code contract and
status-document shape with automated tests, matching the focused-module
precedent (test_bug4_multiplex_paths.py, test_bug3_multi_profile_cron.py) so
parallel plans in later waves do not serialize on the monolithic test file.

Mirrors tests.test_repository.RepositoryTests.test_hooks_status_sh_three_verdicts's
per-branch tempfile.mkdtemp + try/finally shutil.rmtree + scratch-scripts-tree shape.
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

CONTRACT_KEYS = {'healthy', 'registered', 'liveness', 'lastChecked'}
LIVENESS_VALUES = {'unknown', 'idle', 'firing', 'stalled'}

# Task 1 (28-03): small settle window so the aged-sentinel branch doesn't
# need a multi-minute-old fixture — os.utime sets deterministic mtimes
# instead of depending on wall-clock test runtime.
SETTLE_SECONDS = 120


def setup_skill_tree(hermes_home):
    """Create <hermes_home>/skills/revenium/scripts and copy common.sh +
    plugin-status.sh into it. Returns the scripts directory path."""
    scripts_dir = os.path.join(hermes_home, 'skills', 'revenium', 'scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    for name in ('common.sh', 'plugin-status.sh'):
        shutil.copy(str(SKILL / 'scripts' / name), scripts_dir)
    return scripts_dir


def seed_state_db(hermes_home, ended_ats):
    """Create <hermes_home>/state.db with a minimal `sessions` table and one
    row per entry in ended_ats (a list of epoch-second floats/ints, or None
    for a row with no ended_at)."""
    db_path = os.path.join(hermes_home, 'state.db')
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, ended_at REAL)')
        for i, ended_at in enumerate(ended_ats):
            conn.execute(
                'INSERT INTO sessions (id, ended_at) VALUES (?, ?)',
                (f'sess-{i}', ended_at),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def write_hermes_shim(bin_dir):
    """Write an argv-logging fake `hermes` binary into bin_dir. Returns the
    path to the argv log the shim appends to (one line per invocation, the
    invocation's full "$*").

    Placement is load-bearing (Task 2 <action>): this MUST live at
    <shim_home>/.local/bin/hermes with HOME set to <shim_home> and PATH
    prepending that directory. ensure_path (common.sh) prepends
    "${HOME}/.local/bin" last, which makes it win PATH resolution over any
    stub placed elsewhere — and, on a host with a REAL `hermes` CLI already
    on PATH (as this repo's own dev machines do), placing the stub anywhere
    else lets the real binary run instead, against real Hermes state.
    """
    import shlex
    os.makedirs(bin_dir, exist_ok=True)
    argv_log = os.path.join(bin_dir, 'hermes.argv.log')
    shim_path = os.path.join(bin_dir, 'hermes')
    with open(shim_path, 'w') as f:
        f.write(
            '#!/usr/bin/env bash\n'
            "printf '%s\\n' \"$*\" >> " + shlex.quote(argv_log) + '\n'
            'exit 0\n'
        )
    os.chmod(shim_path, 0o755)
    return argv_log


def touch_sentinel(markers_ready_dir, name, age_seconds):
    """Create an empty sentinel file at markers_ready_dir/name and set its
    mtime to age_seconds in the past (0 = now) via os.utime, so freshness
    assertions are deterministic rather than runtime-dependent."""
    os.makedirs(markers_ready_dir, exist_ok=True)
    path = os.path.join(markers_ready_dir, name)
    Path(path).touch()
    ts = time.time() - age_seconds
    os.utime(path, (ts, ts))
    return path


class Phase28PluginStatusTests(unittest.TestCase):
    def test_plugin_status_sh_unregistered_missing_dir(self):
        """Exits 1 when the plugin destination directory is absent, even if
        config.yaml lists the plugin in plugins.enabled."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-missing-dir-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            os.makedirs(hermes_home, exist_ok=True)
            # config.yaml DOES list the plugin, but no plugins/ dir exists at all.
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 1,
                f'expected exit 1 (missing dir), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertFalse(data['registered'])
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_unregistered_missing_config_entry(self):
        """Exits 1 when the destination directory exists but config.yaml has
        no matching plugins.enabled list item."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-missing-cfg-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            # config.yaml exists and has a plugins.enabled block, but it does
            # not list revenium-classifier.
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - some-other-plugin\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 1,
                f'expected exit 1 (missing config entry), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertFalse(data['registered'])
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_registered_exits_zero(self):
        """Exits 0 when both the plugin directory and the plugins.enabled
        entry hold; the status document records registered true."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-registered-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                f'expected exit 0 (registered), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertTrue(data['registered'])
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sh_status_document_shape(self):
        """The status document is valid JSON carrying exactly the contract
        key set on both the exit-1 and exit-0 paths; healthy is a bool and
        liveness is one of the four contract values; brokenAt is present on
        the unhealthy path and absent on the healthy path."""
        # --- Unhealthy (exit-1) branch — its own isolated tempdir ----------
        tmp_unreg = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-shape-unreg-')
        try:
            hermes_home = os.path.join(tmp_unreg, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            data = json.loads(Path(status_file).read_text())
            self.assertEqual(set(data.keys()), CONTRACT_KEYS | {'brokenAt'})
            self.assertIsInstance(data['healthy'], bool)
            self.assertFalse(data['healthy'])
            self.assertIn(data['liveness'], LIVENESS_VALUES)
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp_unreg, ignore_errors=True)

        # --- Healthy (exit-0) branch — its own isolated tempdir ------------
        tmp_reg = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-shape-reg-')
        try:
            hermes_home = os.path.join(tmp_reg, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            os.makedirs(plugin_dir, exist_ok=True)
            with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
                f.write('plugins:\n  enabled:\n    - revenium-classifier\n')
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            }
            subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            data = json.loads(Path(status_file).read_text())
            self.assertEqual(set(data.keys()), CONTRACT_KEYS)
            self.assertIsInstance(data['healthy'], bool)
            self.assertTrue(data['healthy'])
            self.assertIn(data['liveness'], LIVENESS_VALUES)
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp_reg, ignore_errors=True)

    def test_plugin_status_sh_never_probes_hermes_cli_for_verdict(self):
        """Source invariant, revised for Task 2 (D-05/D-06): the two verdict
        stages (registration + liveness) never shell out to the Hermes CLI,
        and the script never takes a repair action (gateway restart, plugin
        reinstall, `hermes plugins` probe). The ONLY sanctioned Hermes CLI
        invocation anywhere in the script is the Task 2 not-broken-to-broken
        notification dispatch via `hermes chat --toolsets messaging` — if a
        `command -v hermes` probe is present at all, it must be paired with
        that exact dispatch, never with a repair-oriented invocation.
        Comment lines are filtered out first so a header comment explaining
        this invariant cannot itself trip the assertion."""
        text = (SKILL / 'scripts' / 'plugin-status.sh').read_text()
        code_lines = [
            line for line in text.splitlines()
            if not line.strip().startswith('#')
        ]
        code_text = '\n'.join(code_lines)
        self.assertNotIn('hermes gateway', code_text)
        self.assertNotIn('hermes plugins', code_text)
        self.assertNotIn('hermes restart', code_text)
        if 'command -v hermes' in code_text:
            self.assertIn('hermes chat --toolsets messaging', code_text)

    # -- Task 1: stage-2 liveness -------------------------------------------

    def _registered_fixture(self, hermes_home):
        """Write config.yaml + plugins/revenium-classifier so stage 1 passes."""
        plugin_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(hermes_home, 'config.yaml'), 'w') as f:
            f.write('plugins:\n  enabled:\n    - revenium-classifier\n')

    def test_plugin_status_no_state_db_is_idle(self):
        """Registered plugin, no state.db at all -> exit 0, liveness idle,
        healthy true."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-no-db-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            # Deliberately no state.db written at all.
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                f'expected exit 0 (idle, no state.db), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertEqual(data['liveness'], 'idle')
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_idle_host_not_broken(self):
        """Registered plugin, state.db present with zero sessions whose
        ended_at falls inside the window -> exit 0, liveness idle, healthy
        true. An idle host is never reported broken (D-02)."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-idle-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            # One session, but ended well outside the settle window.
            seed_state_db(hermes_home, [time.time() - (SETTLE_SECONDS * 10)])
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                f'expected exit 0 (idle), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertEqual(data['liveness'], 'idle')
            self.assertNotIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_firing(self):
        """Registered plugin, one session ended inside the window, one
        sentinel file freshly modified in MARKERS_READY_DIR -> exit 0,
        liveness firing, healthy true. NO marker file is ever created here,
        proving liveness never depends on marker content (TRACE-04)."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-firing-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            seed_state_db(hermes_home, [time.time() - 5])
            markers_ready_dir = os.path.join(state_dir, 'markers', '.ready')
            touch_sentinel(markers_ready_dir, 'sess-0', age_seconds=1)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                f'expected exit 0 (firing), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertEqual(data['liveness'], 'firing')
            self.assertNotIn('brokenAt', data)
            # No marker file anywhere under markers/ (only markers/.ready/
            # holds the sentinel) — proves liveness is marker-independent.
            markers_dir = os.path.join(state_dir, 'markers')
            marker_files = [
                p for p in Path(markers_dir).rglob('*')
                if p.is_file() and '.ready' not in p.parts
            ]
            self.assertEqual(marker_files, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_stalled_no_sentinels(self):
        """Registered plugin, one session aged past the settle window with
        MARKERS_READY_DIR empty -> exit 2, liveness stalled, healthy false,
        brokenAt present.

        The session must be OLDER than SETTLE_SECONDS: per D-02 the stall bar
        is the settle window itself, so a sentinel-less session only counts as
        evidence of a stall once the reporter would have given up waiting for
        it. A 5-second-old session with no sentinel yet is a normal in-flight
        session, not a broken classifier."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-stalled-empty-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            seed_state_db(hermes_home, [time.time() - (SETTLE_SECONDS * 1.5)])
            # MARKERS_READY_DIR left empty (but present, mirroring
            # common.sh's own mkdir -p of it).
            os.makedirs(os.path.join(state_dir, 'markers', '.ready'), exist_ok=True)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 2,
                f'expected exit 2 (stalled, empty ready dir), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertEqual(data['liveness'], 'stalled')
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_stalled_aged_sentinel(self):
        """Classifier fired in the past but not for the session that has now
        aged out: a sentinel exists in the ready dir, but it belongs to a
        DIFFERENT (older) session -> exit 2, liveness stalled.

        This is the faithful shape of "stale classifier". The previous fixture
        gave the recently-ended session its OWN sentinel and relied on that
        file's mtime being old — a state that cannot occur in production, since
        a sentinel is written at session end and therefore always carries
        roughly that session's end time. Liveness now matches each session to
        its own sentinel by name, so staleness is expressed by absence for the
        settled session, not by an implausible mtime on a present one."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-stalled-aged-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            seed_state_db(hermes_home, [time.time() - (SETTLE_SECONDS * 1.5)])
            markers_ready_dir = os.path.join(state_dir, 'markers', '.ready')
            # A sentinel from an earlier, unrelated session — proof the
            # classifier once ran, but not for sess-0, which has now settled.
            touch_sentinel(
                markers_ready_dir, 'sess-from-a-previous-run',
                age_seconds=SETTLE_SECONDS * 5,
            )
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 2,
                f'expected exit 2 (stalled, aged sentinel), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertEqual(data['liveness'], 'stalled')
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_partial_miss_is_stalled(self):
        """Three sessions settle; only ONE receives a sentinel -> exit 2,
        liveness stalled.

        Greptile P1 regression. The pre-fix check counted fresh files in the
        shared .ready directory and asked only "is anything fresh here?", so a
        single sentinel vouched for every session that ended in the window: a
        classifier firing for 1 of 3 sessions read as healthy, the broken-state
        alert never fired, and the two missed sessions surfaced downstream as
        `no_job_classified` — reporting a plugin execution failure as "this
        session had no job to classify". Under directory-freshness semantics
        this fixture yields firing/exit 0; it must now yield stalled/exit 2."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-partial-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            aged = time.time() - (SETTLE_SECONDS * 1.5)
            seed_state_db(hermes_home, [aged, aged, aged])
            markers_ready_dir = os.path.join(state_dir, 'markers', '.ready')
            # sess-0 classified; sess-1 and sess-2 silently missed.
            touch_sentinel(markers_ready_dir, 'sess-0', age_seconds=1)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 2,
                'a fresh sentinel for one session must not vouch for two '
                f'others; got {result.returncode}:\n{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertEqual(data['liveness'], 'stalled')
            self.assertIn('brokenAt', data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_sentinel_less_session_within_grace_is_not_stalled(self):
        """A session that ended seconds ago with no sentinel yet -> exit 0,
        liveness firing.

        The counterweight to the partial-miss test: per-session matching must
        not turn the normal asynchronous gap between session end and sentinel
        write into a fleet-wide alert. Only sessions that have aged past
        SETTLE_SECONDS — the bar at which hermes-report.sh stops waiting —
        count as evidence of a stall."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-grace-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            self._registered_fixture(hermes_home)
            seed_state_db(hermes_home, [time.time() - 5])
            os.makedirs(os.path.join(state_dir, 'markers', '.ready'), exist_ok=True)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                'an in-flight session must not be reported as a stall; '
                f'got {result.returncode}:\n{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertTrue(data['healthy'])
            self.assertEqual(data['liveness'], 'firing')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_unregistered_short_circuits_stage_two(self):
        """Unregistered plugin with recent sessions and fresh sentinels ->
        still exit 1 (stage 1 short-circuits before stage 2 runs)."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-unreg-shortcircuit-')
        try:
            hermes_home = os.path.join(tmp, '.hermes')
            scripts_dir = setup_skill_tree(hermes_home)
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            status_file = os.path.join(state_dir, 'plugin-status.json')
            # Deliberately NOT registered: no plugins/ dir, no config.yaml entry.
            seed_state_db(hermes_home, [time.time() - 5])
            markers_ready_dir = os.path.join(state_dir, 'markers', '.ready')
            touch_sentinel(markers_ready_dir, 'sess-0', age_seconds=1)
            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_PLUGIN_STATUS_FILE': status_file,
                'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 1,
                f'expected exit 1 (unregistered short-circuits stage 2), got {result.returncode}:\n'
                f'{result.stdout}\n{result.stderr}',
            )
            data = json.loads(Path(status_file).read_text())
            self.assertFalse(data['healthy'])
            self.assertFalse(data['registered'])
            self.assertEqual(data['liveness'], 'unknown')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # -- Task 2: not-broken-to-broken transition + notification -------------

    def _stalled_fixture_env(self, tmp, notify_channel=None, notify_target=None):
        """Build a registered-but-stalled fixture: one session that has aged
        PAST the settle window with MARKERS_READY_DIR empty, so it counts as a
        genuine stall rather than a session still legitimately in flight.
        Returns
        (scripts_dir, status_file, log_file, base_env_dict) — base_env_dict
        has no HOME/PATH override yet; callers add those per-test so each
        test controls hermes-CLI visibility explicitly (never inherit the
        real dev machine's `hermes` unintentionally)."""
        hermes_home = os.path.join(tmp, '.hermes')
        scripts_dir = setup_skill_tree(hermes_home)
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        status_file = os.path.join(state_dir, 'plugin-status.json')
        log_file = os.path.join(state_dir, 'revenium-metering.log')
        self._registered_fixture(hermes_home)
        seed_state_db(hermes_home, [time.time() - (SETTLE_SECONDS * 1.5)])
        os.makedirs(os.path.join(state_dir, 'markers', '.ready'), exist_ok=True)
        config = {}
        if notify_channel is not None:
            config['notifyChannel'] = notify_channel
        if notify_target is not None:
            config['notifyTarget'] = notify_target
        os.makedirs(state_dir, exist_ok=True)
        with open(os.path.join(state_dir, 'config.json'), 'w') as f:
            json.dump(config, f)
        base_env = {
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'REVENIUM_PLUGIN_STATUS_FILE': status_file,
            'REVENIUM_CRON_SETTLE_SECONDS': str(SETTLE_SECONDS),
        }
        return scripts_dir, status_file, log_file, base_env

    def test_plugin_status_broken_transition_notifies_once(self):
        """First run resolving broken against an absent prior status file
        emits the transition marker on stdout and, with a notify channel
        configured, dispatches exactly one message whose first token is
        'chat' — proving the only use of the tool is notification dispatch."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-notify-once-')
        try:
            scripts_dir, status_file, log_file, base_env = self._stalled_fixture_env(
                tmp, notify_channel='slack', notify_target='#ops',
            )
            shim_home = os.path.join(tmp, 'shimhome')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            argv_log = write_hermes_shim(bin_dir)
            env = {
                **os.environ,
                **base_env,
                'HOME': shim_home,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }

            # Snapshot mtimes of the things this script only INSPECTS, never
            # mutates: the plugin destination directory and config.yaml.
            hermes_home = base_env['HERMES_HOME']
            plugin_dest_dir = os.path.join(hermes_home, 'plugins', 'revenium-classifier')
            config_yaml = os.path.join(hermes_home, 'config.yaml')
            mtime_plugin_before = os.path.getmtime(plugin_dest_dir)
            mtime_config_before = os.path.getmtime(config_yaml)

            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(
                'PLUGIN_BROKEN_TRANSITION=true', result.stdout,
                f'expected transition marker on first broken run; stdout={result.stdout!r}',
            )
            self.assertTrue(
                os.path.isfile(argv_log),
                'hermes shim argv log not found — notification dispatch never reached the shim',
            )
            with open(argv_log) as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(
                len(lines), 1,
                f'expected exactly 1 dispatch on the first broken run; got {lines!r}',
            )
            self.assertEqual(
                lines[0].split()[0], 'chat',
                f'the only sanctioned hermes invocation is `hermes chat ...`; got {lines[0]!r}',
            )

            # The script must mutate nothing it inspects.
            self.assertEqual(
                os.path.getmtime(plugin_dest_dir), mtime_plugin_before,
                'plugin destination directory mtime changed — the script must never write to it',
            )
            self.assertEqual(
                os.path.getmtime(config_yaml), mtime_config_before,
                'config.yaml mtime changed — the script must never write to it',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_repeat_broken_is_silent(self):
        """A second run against the same still-broken fixture emits no
        transition marker and dispatches zero additional messages."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-notify-repeat-')
        try:
            scripts_dir, status_file, log_file, base_env = self._stalled_fixture_env(
                tmp, notify_channel='slack', notify_target='#ops',
            )
            shim_home = os.path.join(tmp, 'shimhome')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            argv_log = write_hermes_shim(bin_dir)
            env = {
                **os.environ,
                **base_env,
                'HOME': shim_home,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            result1 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertIn('PLUGIN_BROKEN_TRANSITION=true', result1.stdout)
            with open(argv_log) as f:
                lines_after_1 = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(len(lines_after_1), 1)

            result2 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result2.returncode, 2, result2.stdout + result2.stderr)
            self.assertIn(
                'PLUGIN_BROKEN_TRANSITION=false', result2.stdout,
                f'second run against unchanged broken fixture must NOT re-transition; '
                f'stdout={result2.stdout!r}',
            )
            with open(argv_log) as f:
                lines_after_2 = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(
                len(lines_after_2), 1,
                f'repeat broken tick must dispatch zero additional messages; got {lines_after_2!r}',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_no_channel_configured(self):
        """A broken run with no notifyChannel/notifyTarget configured logs
        an informational line and still exits with the verdict's exit code —
        it never fails the script."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-no-channel-')
        try:
            scripts_dir, status_file, log_file, base_env = self._stalled_fixture_env(tmp)
            shim_home = os.path.join(tmp, 'shimhome')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir, exist_ok=True)
            env = {
                **os.environ,
                **base_env,
                'HOME': shim_home,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertTrue(os.path.isfile(log_file), 'revenium-metering.log must exist')
            log_text = Path(log_file).read_text()
            self.assertIn(
                '[INFO ]', log_text,
                f'expected an informational log line when no channel is configured; log={log_text!r}',
            )
            self.assertIn('no notification channel configured', log_text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_messaging_tool_absent(self):
        """A broken run with the messaging CLI absent from PATH logs a
        warning and still exits with the verdict's exit code. PATH is
        restricted to a fixed, known-safe set (never inheriting the real
        dev machine's PATH) so this test cannot accidentally find and
        invoke a REAL `hermes` binary."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-no-tool-')
        try:
            scripts_dir, status_file, log_file, base_env = self._stalled_fixture_env(
                tmp, notify_channel='slack', notify_target='#ops',
            )
            shim_home = os.path.join(tmp, 'shimhome')
            # Deliberately empty — no hermes shim written here.
            os.makedirs(shim_home, exist_ok=True)
            env = {
                **os.environ,
                **base_env,
                'HOME': shim_home,
                # Fixed minimal PATH: enough for bash/python3/sqlite3 to
                # resolve, but excludes any real hermes install location.
                'PATH': '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin',
            }
            result = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertTrue(os.path.isfile(log_file), 'revenium-metering.log must exist')
            log_text = Path(log_file).read_text()
            self.assertIn(
                '[WARN ]', log_text,
                f'expected a warning log line when the messaging tool is absent; log={log_text!r}',
            )
            self.assertIn('hermes CLI not available', log_text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_plugin_status_recovery_clears_broken_at(self):
        """A run that resolves back to healthy after a broken run clears
        brokenAt and emits no notification."""
        tmp = tempfile.mkdtemp(prefix='gsd-phase28-plugstat-recovery-')
        try:
            scripts_dir, status_file, log_file, base_env = self._stalled_fixture_env(
                tmp, notify_channel='slack', notify_target='#ops',
            )
            hermes_home = base_env['HERMES_HOME']
            state_dir = base_env['REVENIUM_STATE_DIR']
            shim_home = os.path.join(tmp, 'shimhome')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            argv_log = write_hermes_shim(bin_dir)
            env = {
                **os.environ,
                **base_env,
                'HOME': shim_home,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            }
            result1 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result1.returncode, 2, result1.stdout + result1.stderr)
            data1 = json.loads(Path(status_file).read_text())
            self.assertIn('brokenAt', data1)

            # Recover: add a freshly-touched sentinel so this tick resolves firing.
            markers_ready_dir = os.path.join(state_dir, 'markers', '.ready')
            touch_sentinel(markers_ready_dir, 'sess-0', age_seconds=1)

            result2 = subprocess.run(
                ['bash', os.path.join(scripts_dir, 'plugin-status.sh')],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result2.returncode, 0,
                f'expected exit 0 on recovery, got {result2.returncode}:\n'
                f'{result2.stdout}\n{result2.stderr}',
            )
            data2 = json.loads(Path(status_file).read_text())
            self.assertTrue(data2['healthy'])
            self.assertNotIn('brokenAt', data2, 'brokenAt must be cleared on recovery')
            self.assertIn(
                'PLUGIN_BROKEN_TRANSITION=false', result2.stdout,
                f'a recovery run must not be a broken-transition; stdout={result2.stdout!r}',
            )
            with open(argv_log) as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(
                len(lines), 1,
                f'recovery run must dispatch zero additional notifications '
                f'(only the first broken run should have dispatched); got {lines!r}',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
