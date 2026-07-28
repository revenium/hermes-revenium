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
import os
import shutil
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
