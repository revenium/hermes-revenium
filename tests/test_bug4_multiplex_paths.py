"""BUG-4 regression: multiplex per-session path resolution.

In gateway.multiplex_profiles mode ONE default gateway process serves every
profile; sessions are namespaced `agent:<profile>:…` and each profile keeps its
own home/state.db/markers under ~/.hermes/profiles/<profile>/ (see
user-guide/multi-profile-gateways.md). The classifier's module-level path
constants are import-time snapshots of the PROCESS env, so without per-session
resolution every profile's markers/sentinels land in the DEFAULT home and the
per-profile cron never sees them.

These tests pin: (1) _paths_for_session redirects a namespaced session to the
owning profile's dirs when that profile home exists, and falls back to the module
paths otherwise (default profile, non-namespaced session, or profile home absent
— the one-process-per-profile case); (2) a marker written for a namespaced
session lands under the OWNING profile's markers dir, not the default home's.
"""
import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "skills" / "revenium" / "plugins" / "revenium-classifier"


class TestBug4MultiplexPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-bug4-multiplex-")
        # Default home (the multiplexer process's HERMES_HOME).
        self.dh = os.path.join(self.tmp, ".hermes")
        os.makedirs(os.path.join(self.dh, "state", "revenium", "markers", ".ready"),
                    exist_ok=True)
        # An existing profile home for 'gtm' (multiplex serves it from the default gw).
        self.gtm = os.path.join(self.dh, "profiles", "gtm")
        os.makedirs(os.path.join(self.gtm, "state", "revenium", "markers", ".ready"),
                    exist_ok=True)

        self._snapshot = {k: os.environ.get(k) for k in (
            "HERMES_HOME", "REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
            "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
            "REVENIUM_JOB_TAXONOMY_FILE",
        )}
        # Point the process at the DEFAULT home; clear per-path overrides so the
        # module derives the canonical layout from HERMES_HOME.
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
        # Restore env and reload the module WHILE PLUGIN_DIR is still importable,
        # so the module globals reflect the restored env for later tests.
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

    def test_namespaced_session_redirects_to_profile_home(self):
        p = self.classifier._paths_for_session("agent:gtm:sess-1")
        self.assertEqual(
            Path(p.markers_dir),
            Path(self.gtm) / "state" / "revenium" / "markers",
            "namespaced session did not resolve to the owning profile's markers dir",
        )
        self.assertEqual(Path(p.state_db), Path(self.gtm) / "state.db")
        self.assertEqual(
            Path(p.markers_ready_dir),
            Path(self.gtm) / "state" / "revenium" / "markers" / ".ready",
        )

    def test_default_and_plain_sessions_use_module_paths(self):
        mod = self.classifier._module_paths()
        for sid in ("plain-session-id", "agent:default:sess-9"):
            p = self.classifier._paths_for_session(sid)
            self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir),
                             f"{sid} should resolve to the module (default) paths")

    def test_absent_profile_home_falls_back_to_module_paths(self):
        # One-process-per-profile mode: namespaced id but no profiles/<x>/ under
        # this process's home -> use the module paths (process home is already right).
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("agent:doesnotexist:sess-1")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_marker_lands_in_owning_profile_dir(self):
        sid = "agent:gtm:sess-42"
        p = self.classifier._paths_for_session(sid)
        self.classifier._write_marker_pair(sid, "code_review", p)

        profile_marker = Path(self.gtm) / "state" / "revenium" / "markers" / f"{sid}.jsonl"
        default_marker = Path(self.dh) / "state" / "revenium" / "markers" / f"{sid}.jsonl"
        self.assertTrue(profile_marker.is_file(),
                        "marker did not land under the owning profile's dir")
        self.assertFalse(default_marker.exists(),
                         "BUG-4 REGRESSION: marker leaked into the default home's dir")
        # And a job marker too.
        self.classifier._write_job_marker(
            sid, {"agentic_job_id": "j1", "job_name": "n", "job_type": "review",
                  "status": "SUCCESS", "failure_reason": ""}, p)
        self.assertIn("kind", profile_marker.read_text())
        # The sentinel dir __init__._write_sentinel uses is exactly this value —
        # asserted in test_namespaced_session_redirects_to_profile_home — so the
        # sentinel lands under the owning profile's .ready dir too.


if __name__ == "__main__":
    unittest.main()
