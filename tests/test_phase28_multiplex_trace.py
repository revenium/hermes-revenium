"""Phase 28 (TRACE-03): parity proof between the classifier's per-session
markers-directory resolution and the cron-side sidecar mirror.

`classifier._paths_for_session` (skills/revenium/plugins/revenium-classifier/
classifier.py:90-125) fully resolves namespaced `agent:<profile>:` sessions to
per-profile directories on the WRITE side (inside Hermes' process).
`skills/revenium/scripts/resolve-markers-dir.py` deliberately reimplements
that same resolution on the READ side (inside the cron process, which cannot
import the classifier module — see that sidecar's docstring for the
rationale). Nothing structurally prevents the two implementations from
drifting apart; this module is the only mechanism that keeps the mirror
honest, by driving BOTH implementations over one shared identifier set in
one process and asserting byte-identical results.

This module is extended by Plan 28-07 with the end-to-end fixture, so setup
is factored into reusable helpers rather than inlined into one test.
"""
import importlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "revenium"
PLUGIN_DIR = SKILL / "plugins" / "revenium-classifier"
SIDECAR = SKILL / "scripts" / "resolve-markers-dir.py"
COMMON_SH = SKILL / "scripts" / "common.sh"

# Shared identifier set covering every session-identifier shape the
# classifier's own resolver handles. Every test in this module drives BOTH
# implementations over this one sequence so no test can narrow coverage
# without narrowing all of them.
IDENTIFIER_SET = (
    "agent:gtm:sess-1",              # namespaced, existing profile
    "plain-session-id",              # non-namespaced
    "agent:default:sess-9",          # namespaced to the default profile
    "agent:doesnotexist:sess-1",     # namespaced, profile absent on disk
    "",                              # empty identifier
    "agent:../../etc:sess-1",        # traversal-shaped profile segment
)


def _load_sidecar():
    """Load resolve-markers-dir.py as an importable module.

    The sidecar's filename contains hyphens, forbidding `import` syntax — same
    technique tests/test_repository.py uses for the get-root-session-id.py
    sidecar (_load_root_walk_helper).
    """
    spec = importlib.util.spec_from_file_location(
        "phase28_resolve_markers_dir", str(SIDECAR),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Phase28MultiplexTraceParityTests(unittest.TestCase):
    def setUp(self):
        # Clone tests/test_bug4_multiplex_paths.py's setUp wholesale: a
        # temporary root, a default Hermes home, a second profile home under
        # the default home's profiles subdirectory, an environment snapshot
        # covering every path override variable, the plugin directory pushed
        # onto the module search path, and importlib.reload of the classifier
        # module so its import-time path constants reflect the temp env.
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase28-multiplex-trace-")
        self.dh = os.path.join(self.tmp, ".hermes")
        os.makedirs(os.path.join(self.dh, "state", "revenium", "markers", ".ready"), exist_ok=True)
        self.gtm = os.path.join(self.dh, "profiles", "gtm")
        os.makedirs(os.path.join(self.gtm, "state", "revenium", "markers", ".ready"), exist_ok=True)

        self._snapshot = {k: os.environ.get(k) for k in (
            "HERMES_HOME", "REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
            "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
            "REVENIUM_JOB_TAXONOMY_FILE",
        )}
        os.environ["HERMES_HOME"] = self.dh
        for k in ("REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
                  "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
                  "REVENIUM_JOB_TAXONOMY_FILE"):
            os.environ.pop(k, None)

        self._path_added = str(PLUGIN_DIR) not in sys.path
        if self._path_added:
            sys.path.insert(0, str(PLUGIN_DIR))
        import classifier
        self.classifier = importlib.reload(classifier)
        self.sidecar = _load_sidecar()

    def tearDown(self):
        # Restore the environment and reload WHILE PLUGIN_DIR is still
        # importable, so module globals reflect the restored env for later
        # test modules — skipping this leaves later tests resolving against
        # a deleted temporary directory.
        for k, v in self._snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import classifier
            importlib.reload(classifier)
        except Exception:
            pass
        if self._path_added and str(PLUGIN_DIR) in sys.path:
            sys.path.remove(str(PLUGIN_DIR))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sidecar_matches_classifier_for_every_identifier_shape(self):
        for sid in IDENTIFIER_SET:
            classifier_dir = str(self.classifier._paths_for_session(sid).markers_dir)
            sidecar_dir = self.sidecar.resolve_markers_dir(sid)
            self.assertEqual(
                classifier_dir, sidecar_dir,
                f"resolver disagreement for identifier {sid!r}: "
                f"classifier={classifier_dir!r} sidecar={sidecar_dir!r}",
            )

    def test_traversal_shaped_profile_falls_back(self):
        sid = "agent:../../etc:sess-1"
        module_dir = str(self.classifier._module_paths().markers_dir)
        classifier_dir = str(self.classifier._paths_for_session(sid).markers_dir)
        sidecar_dir = self.sidecar.resolve_markers_dir(sid)
        self.assertEqual(classifier_dir, module_dir,
                          "classifier should fall back to module paths for a traversal-shaped profile")
        self.assertEqual(sidecar_dir, module_dir,
                          "sidecar should fall back to module (process-level) markers dir")

    def test_shell_wrapper_matches_sidecar(self):
        sid = "agent:gtm:sess-1"
        expected = self.sidecar.resolve_markers_dir(sid)
        driver = self._write_driver("driver.sh", sid)
        result = subprocess.run(
            ["bash", driver], capture_output=True, text=True,
            env=dict(os.environ), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expected)

    def test_shell_wrapper_fails_open_without_interpreter(self):
        sid = "agent:gtm:sess-1"
        expected = str(self.classifier._module_paths().markers_dir)
        driver = self._write_driver("driver-no-python.sh", sid)

        # A PATH containing bash but deliberately no python3 anywhere on it —
        # a fixed empty temp dir plus bash's own directory, NOT the real
        # system PATH (which would still find python3).
        empty_path_dir = os.path.join(self.tmp, "empty-bin")
        os.makedirs(empty_path_dir, exist_ok=True)
        bash_path = shutil.which("bash") or "/bin/bash"
        env = dict(os.environ)
        env["PATH"] = f"{empty_path_dir}:{os.path.dirname(bash_path)}"

        result = subprocess.run(
            ["bash", driver], capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expected)

    def _write_driver(self, name, sid):
        driver = os.path.join(self.tmp, name)
        with open(driver, "w") as f:
            f.write(
                "#!/usr/bin/env bash\n"
                "set -uo pipefail\n"
                f'source "{COMMON_SH}"\n'
                f'resolve_markers_dir "{sid}"\n'
            )
        os.chmod(driver, 0o755)
        return driver


# --- Plan 28-07: end-to-end reporter harness -------------------------------
#
# Reporter-subprocess scripts needed for a self-contained SKILL_DIR (mirrors
# tests/test_repository.py's test_hermes_report_subagent_trace_inheritance
# harness, extended with resolve-markers-dir.py — Task 1's new read-side
# dependency).
_REPORTER_SCRIPTS = (
    "common.sh", "hermes-report.sh", "get-root-session-id.py",
    "resolve-markers-dir.py", "split_strategies.py",
)


def _seed_sessions_db(db_path, rows, age_seconds=300):
    """Create the sessions table (schema cloned from tests/test_repository.py's
    subagent-trace-inheritance harness) and insert one row per
    (sid, parent_sid_or_none, input_tokens, output_tokens) tuple, all aged
    `age_seconds` in the past so they clear the pinned settle window
    regardless of sentinel presence."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, model TEXT, source TEXT,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                reasoning_tokens INTEGER, estimated_cost_usd REAL,
                api_call_count INTEGER, started_at REAL, ended_at REAL,
                billing_provider TEXT, parent_session_id TEXT
            )
            """
        )
        old_ts = time.time() - age_seconds
        conn.executemany(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (sid, "claude-sonnet-4", "cli", inp, out, 0, 0, 0,
                 0.01, 1, old_ts, old_ts, "anthropic", parent)
                for sid, parent, inp, out in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _write_job_marker_file(markers_dir, sid, job_type, agentic_job_id):
    """Directly write a kind:"job" marker line for a NON-namespaced session
    (no classifier/profile resolution involved — used by the plain
    single-profile fixtures where the marker's location is simply the
    process-level markers directory)."""
    os.makedirs(markers_dir, exist_ok=True)
    with open(os.path.join(markers_dir, f"{sid}.jsonl"), "w") as f:
        f.write(json.dumps({
            "kind": "job", "ts": time.time(), "sid": sid,
            "agentic_job_id": agentic_job_id, "job_name": f"{job_type} job",
            "job_type": job_type, "status": "SUCCESS",
        }) + "\n")


def _fake_revenium_script(argv_log):
    """Argv-logging fake `revenium` binary. Advertises BOTH the job-identifier
    flag and the trace-type flag on its `meter completion --help` output so
    both capability probes (JOBS_CLI_CAPABLE, TRACE_TYPE_CLI_CAPABLE) pass."""
    return (
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "' + argv_log + '"\n'
        'case "$1 $2 $3" in\n'
        '  "config show "* | "config show")\n'
        '    echo "api_key: mock"; exit 0 ;;\n'
        '  "jobs --help "* | "jobs --help")\n'
        "    exit 0 ;;\n"
        '  "meter completion --help")\n'
        '    echo "--agentic-job-id"; echo "--trace-type"; exit 0 ;;\n'
        '  "jobs create "*)\n'
        "    echo '{\"id\":\"job-id\"}'; exit 0 ;;\n"
        "  *)\n"
        "    exit 0 ;;\n"
        "esac\n"
    )


def _meter_completion_lines(argv_text, sid):
    """argv lines that are a `meter completion` call carrying `sid` — used
    for single-session fixtures where no other sid's transaction-id could
    collide."""
    return [
        line for line in argv_text.splitlines()
        if "meter completion" in line and sid in line
    ]


def _own_meter_lines(argv_text, own_sid, other_sids=()):
    """argv lines that are a `meter completion` call for `own_sid`
    specifically — containing `own_sid` (its own --transaction-id) and NOT
    any of `other_sids` (which would only appear via another session's own
    --trace-id/--transaction-id, e.g. a sibling's --trace-id pointing at this
    session's root). Mirrors the disambiguation
    test_hermes_report_subagent_trace_inheritance already uses."""
    lines = []
    for line in argv_text.splitlines():
        if "meter completion" not in line or own_sid not in line:
            continue
        if any(other in line for other in other_sids):
            continue
        lines.append(line)
    return lines


def _trace_type_value(line):
    m = re.search(r"--trace-type (\S+)", line)
    return m.group(1) if m else None


class Phase28MultiplexTraceEndToEndTests(unittest.TestCase):
    """TRACE-03 end-to-end reproduction and TRACE-05 sibling-equality
    fixtures for Plan 28-07.

    setUp/tearDown are cloned wholesale from
    Phase28MultiplexTraceParityTests (same temp two-profile layout,
    environment snapshot/restore, plugin sys.path push, classifier reload)
    so the multiplex fixtures below drive the SAME environment shape the
    parity tests already prove agrees between the classifier and the
    sidecar. Reporter-subprocess mechanics (scratch scripts tree, session-db
    schema, settle-window aging, argv-logging fake `revenium`) are cloned
    from tests/test_repository.py's test_hermes_report_subagent_trace_inheritance.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase28-multiplex-e2e-")
        self.dh = os.path.join(self.tmp, ".hermes")
        os.makedirs(os.path.join(self.dh, "state", "revenium", "markers", ".ready"), exist_ok=True)
        self.gtm = os.path.join(self.dh, "profiles", "gtm")
        os.makedirs(os.path.join(self.gtm, "state", "revenium", "markers", ".ready"), exist_ok=True)

        self._snapshot = {k: os.environ.get(k) for k in (
            "HERMES_HOME", "REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
            "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
            "REVENIUM_JOB_TAXONOMY_FILE",
        )}
        os.environ["HERMES_HOME"] = self.dh
        for k in ("REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
                  "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
                  "REVENIUM_JOB_TAXONOMY_FILE"):
            os.environ.pop(k, None)

        self._path_added = str(PLUGIN_DIR) not in sys.path
        if self._path_added:
            sys.path.insert(0, str(PLUGIN_DIR))
        import classifier
        self.classifier = importlib.reload(classifier)

    def tearDown(self):
        for k, v in self._snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import classifier
            importlib.reload(classifier)
        except Exception:
            pass
        if self._path_added and str(PLUGIN_DIR) in sys.path:
            sys.path.remove(str(PLUGIN_DIR))
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- harness helpers ----

    def _build_scripts_dir(self):
        scripts_dir = os.path.join(self.tmp, "harness-scripts", "skills", "revenium", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        for name in _REPORTER_SCRIPTS:
            shutil.copy(str(SKILL / "scripts" / name), scripts_dir)
        return scripts_dir

    def _build_fake_revenium(self):
        shim_home = os.path.join(self.tmp, "home")
        bin_dir = os.path.join(shim_home, ".local", "bin")
        os.makedirs(bin_dir, exist_ok=True)
        argv_log = os.path.join(self.tmp, "revenium.argv.log")
        fake = os.path.join(bin_dir, "revenium")
        with open(fake, "w") as f:
            f.write(_fake_revenium_script(argv_log))
        os.chmod(fake, 0o755)
        return shim_home, bin_dir, argv_log

    def _run_reporter(self, scripts_dir, shim_home, bin_dir):
        env = {
            **os.environ,
            "HOME": shim_home,
            "HERMES_HOME": self.dh,
            "REVENIUM_CRON_SETTLE_SECONDS": "120",
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
        }
        # Load-bearing (T-28-33): clear per-path overrides so common.sh
        # derives the canonical layout from HERMES_HOME, matching the
        # multiplexed-gateway environment the plan's fixture must reproduce.
        for k in ("REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
                  "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
                  "REVENIUM_JOB_TAXONOMY_FILE"):
            env.pop(k, None)
        return subprocess.run(
            ["bash", os.path.join(scripts_dir, "hermes-report.sh")],
            env=env, capture_output=True, text=True, timeout=30,
        )

    def _read_argv_log(self, argv_log, result):
        self.assertTrue(
            os.path.exists(argv_log),
            f"no argv log written; stdout={result.stdout}\nstderr={result.stderr}",
        )
        with open(argv_log) as fh:
            text = fh.read()
        # T-28-36 / plan acceptance criterion: the fake's argv log must be
        # non-empty in every fixture, proving the reporter reached the emit
        # path rather than exiting at a preflight guard.
        self.assertTrue(
            text.strip(),
            f"fake revenium argv log is empty — reporter never reached the "
            f"emit path; stdout={result.stdout}\nstderr={result.stderr}",
        )
        return text

    def _default_markers_dir(self):
        return os.path.join(self.dh, "state", "revenium", "markers")

    # ---- Test 1 (TRACE-03 end to end) ----

    def test_multiplex_trace_type_path_agreement(self):
        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        sid = "agent:gtm:sess-1"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [(sid, None, 100, 50)])

        # Write the job marker by calling the classifier's REAL marker writer
        # through its REAL per-session resolver (D-10) — the marker's
        # location is produced by the code under test, not by this
        # fixture's own assumption about where a namespaced session's
        # markers live.
        p = self.classifier._paths_for_session(sid)
        self.classifier._write_job_marker(
            sid,
            {"agentic_job_id": "job-mx-1", "job_name": "multiplex job",
             "job_type": "code_review", "status": "SUCCESS", "failure_reason": ""},
            p,
        )

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        lines = _meter_completion_lines(argv_text, sid)
        self.assertTrue(lines, f"expected >=1 meter completion for {sid}; argv:\n{argv_text}")
        for line in lines:
            self.assertEqual(
                _trace_type_value(line), "code_review",
                f"namespaced session must carry the classified job type as "
                f"--trace-type by exact match:\n{line}",
            )

    # ---- Test 2 (TRACE-02 positive) ----

    def test_single_profile_trace_type_positive(self):
        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        sid = "plain-root-sess-1"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [(sid, None, 100, 50)])
        _write_job_marker_file(self._default_markers_dir(), sid, "planning", "job-plain-1")

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        lines = _meter_completion_lines(argv_text, sid)
        self.assertTrue(lines, f"expected >=1 meter completion for {sid}; argv:\n{argv_text}")
        for line in lines:
            self.assertEqual(_trace_type_value(line), "planning", line)

    # ---- Test 3 (TRACE-05 adjacency) ----

    def test_sibling_sessions_share_one_trace_type(self):
        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        root_sid = "sibling-root-sess"
        child_sid = "sibling-child-sess"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [
            (root_sid, None, 100, 50),
            (child_sid, root_sid, 200, 100),
        ])
        _write_job_marker_file(self._default_markers_dir(), root_sid, "refactor", "job-sib-1")

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        root_lines = _own_meter_lines(argv_text, root_sid, other_sids=(child_sid,))
        child_lines = _own_meter_lines(argv_text, child_sid, other_sids=())
        self.assertTrue(root_lines, f"expected >=1 root meter completion; argv:\n{argv_text}")
        self.assertTrue(child_lines, f"expected >=1 child meter completion; argv:\n{argv_text}")

        values = set()
        for line in root_lines + child_lines:
            v = _trace_type_value(line)
            self.assertIsNotNone(v, f"no --trace-type in line: {line}")
            values.add(v)
        self.assertEqual(
            len(values), 1,
            f"every completion sharing a trace must carry ONE identical "
            f"--trace-type value; got {values} across:\n{argv_text}",
        )
        self.assertEqual(values, {"refactor"})

    # ---- Test 4 (TRACE-05 empty edge probe) ----

    def test_absent_root_marker_falls_back_uniformly(self):
        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        root_sid = "empty-root-sess"
        child_sid = "empty-child-sess"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [
            (root_sid, None, 100, 50),
            (child_sid, root_sid, 200, 100),
        ])
        # Deliberately no marker file for root_sid anywhere.

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        root_lines = _own_meter_lines(argv_text, root_sid, other_sids=(child_sid,))
        child_lines = _own_meter_lines(argv_text, child_sid, other_sids=())
        self.assertTrue(root_lines, f"expected >=1 root meter completion; argv:\n{argv_text}")
        self.assertTrue(child_lines, f"expected >=1 child meter completion; argv:\n{argv_text}")

        for line in root_lines + child_lines:
            self.assertEqual(
                _trace_type_value(line), "uncategorized",
                f"a trace with no usable root job record must fall back to "
                f"the single fallback literal for every session in it:\n{line}",
            )

    def test_single_session_trace_carries_own_value(self):
        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        sid = "solo-trace-sess"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [(sid, None, 100, 50)])
        _write_job_marker_file(self._default_markers_dir(), sid, "research", "job-solo-1")

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        lines = _meter_completion_lines(argv_text, sid)
        self.assertTrue(lines, f"expected >=1 meter completion for {sid}; argv:\n{argv_text}")
        for line in lines:
            self.assertEqual(_trace_type_value(line), "research", line)

    # ---- Test 5 (no regression) ----

    def test_multiplex_fixture_without_profile_home_matches_single_profile(self):
        # Remove the profile home entirely — the one-process-per-profile
        # shape (or a plain uninstalled-multiplex install), where the
        # resolver must fall back to the process-level (module) markers dir,
        # exactly like today's single-profile behavior.
        shutil.rmtree(self.gtm, ignore_errors=True)
        import classifier
        self.classifier = importlib.reload(classifier)

        scripts_dir = self._build_scripts_dir()
        shim_home, bin_dir, argv_log = self._build_fake_revenium()

        sid = "agent:gtm:sess-1"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [(sid, None, 100, 50)])

        p = self.classifier._paths_for_session(sid)
        self.classifier._write_job_marker(
            sid,
            {"agentic_job_id": "job-mx-2", "job_name": "regression job",
             "job_type": "debugging", "status": "SUCCESS", "failure_reason": ""},
            p,
        )
        # Confirm the marker landed under the MODULE (process-level) dir —
        # the profile home no longer exists, so both the classifier's own
        # resolver and the sidecar mirror must fall back identically.
        module_markers_dir = self.classifier._module_paths().markers_dir
        self.assertTrue(
            (module_markers_dir / f"{sid}.jsonl").is_file(),
            "expected the marker to land in the module (process-level) "
            "markers dir once the profile home is absent",
        )

        result = self._run_reporter(scripts_dir, shim_home, bin_dir)
        argv_text = self._read_argv_log(argv_log, result)

        lines = _meter_completion_lines(argv_text, sid)
        self.assertTrue(lines, f"expected >=1 meter completion for {sid}; argv:\n{argv_text}")
        for line in lines:
            self.assertEqual(_trace_type_value(line), "debugging", line)

    # ---- Test 6 (WR-04 / CR-02 regression: plugin-status.sh liveness under
    # a namespaced, two-profile fixture) ----
    #
    # WR-04: no test combined a namespaced (multiplex) session with
    # plugin-status.sh's liveness verdict before this — exactly the gap that
    # let CR-02 (single-default-profile-scoped liveness check misreporting
    # under gateway.multiplex_profiles) ship undetected. These two tests
    # exercise both directions of that misdiagnosis.

    _PLUGIN_STATUS_SCRIPTS = ("common.sh", "plugin-status.sh", "resolve-markers-dir.py")

    def _build_status_scripts_dir(self):
        scripts_dir = os.path.join(self.tmp, "status-scripts", "skills", "revenium", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        for name in self._PLUGIN_STATUS_SCRIPTS:
            shutil.copy(str(SKILL / "scripts" / name), scripts_dir)
        return scripts_dir

    def _registered_fixture(self):
        """Write config.yaml + plugins/revenium-classifier under self.dh so
        plugin-status.sh's stage-1 registration check passes (mirrors
        Phase28PluginStatusTests._registered_fixture)."""
        plugin_dir = os.path.join(self.dh, "plugins", "revenium-classifier")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(self.dh, "config.yaml"), "w") as f:
            f.write("plugins:\n  enabled:\n    - revenium-classifier\n")

    def _touch_sentinel(self, ready_dir, name, age_seconds):
        os.makedirs(ready_dir, exist_ok=True)
        path = os.path.join(ready_dir, name)
        Path(path).touch()
        ts = time.time() - age_seconds
        os.utime(path, (ts, ts))
        return path

    def _run_plugin_status(self, scripts_dir, settle_seconds, status_file):
        env = {
            **os.environ,
            "HERMES_HOME": self.dh,
            "REVENIUM_PLUGIN_STATUS_FILE": status_file,
            "REVENIUM_CRON_SETTLE_SECONDS": str(settle_seconds),
        }
        # Load-bearing (mirrors _run_reporter): clear per-path overrides so
        # common.sh derives the canonical layout from HERMES_HOME, matching
        # the multiplexed-gateway environment this fixture reproduces.
        for k in ("REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
                  "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
                  "REVENIUM_JOB_TAXONOMY_FILE"):
            env.pop(k, None)
        return subprocess.run(
            ["bash", os.path.join(scripts_dir, "plugin-status.sh")],
            env=env, capture_output=True, text=True, timeout=10,
        )

    def test_multiplex_named_profile_firing_default_idle_no_false_stall(self):
        """A named profile (gtm) with a recently-ended session and a fresh
        sentinel under ITS OWN .ready/ dir, alongside a wholly idle default
        profile, must report liveness=firing/healthy=true — not the false
        stalled verdict CR-02 produced by aggregating gtm's ended session
        against the default profile's (empty) .ready/ dir."""
        settle_seconds = 120
        self._registered_fixture()
        sid = "agent:gtm:sess-1"
        _seed_sessions_db(os.path.join(self.dh, "state.db"), [(sid, None, 100, 50)], age_seconds=5)
        gtm_ready_dir = os.path.join(self.gtm, "state", "revenium", "markers", ".ready")
        self._touch_sentinel(gtm_ready_dir, sid, age_seconds=1)

        scripts_dir = self._build_status_scripts_dir()
        status_file = os.path.join(self.tmp, "plugin-status.json")
        result = self._run_plugin_status(scripts_dir, settle_seconds, status_file)

        self.assertEqual(
            result.returncode, 0,
            f"expected exit 0 (firing), got {result.returncode}:\n{result.stdout}\n{result.stderr}",
        )
        data = json.loads(Path(status_file).read_text())
        self.assertTrue(data["healthy"], data)
        self.assertEqual(data["liveness"], "firing", data)
        self.assertNotIn("brokenAt", data)

    def test_multiplex_named_profile_stalled_not_masked_by_healthy_default(self):
        """The inverse of the above: the default profile is healthy (a
        recently-ended session with a fresh sentinel in its own .ready/
        dir) while a named profile (gtm) has a recently-ended session and
        NO sentinel activity in its own .ready/ dir. The genuinely broken
        gtm classifier must surface as liveness=stalled/healthy=false, not
        be masked by the healthy default profile."""
        settle_seconds = 120
        self._registered_fixture()
        default_sid = "default-sess-1"
        gtm_sid = "agent:gtm:sess-1"
        _seed_sessions_db(
            os.path.join(self.dh, "state.db"),
            [(default_sid, None, 100, 50), (gtm_sid, None, 100, 50)],
            age_seconds=5,
        )
        default_ready_dir = os.path.join(self.dh, "state", "revenium", "markers", ".ready")
        self._touch_sentinel(default_ready_dir, default_sid, age_seconds=1)
        # gtm's own .ready/ dir stays empty (already created in setUp) —
        # its classifier is genuinely not firing.

        scripts_dir = self._build_status_scripts_dir()
        status_file = os.path.join(self.tmp, "plugin-status.json")
        result = self._run_plugin_status(scripts_dir, settle_seconds, status_file)

        self.assertEqual(
            result.returncode, 2,
            f"expected exit 2 (stalled), got {result.returncode}:\n{result.stdout}\n{result.stderr}",
        )
        data = json.loads(Path(status_file).read_text())
        self.assertFalse(data["healthy"], data)
        self.assertEqual(data["liveness"], "stalled", data)
        self.assertIn("brokenAt", data)


if __name__ == "__main__":
    unittest.main()
