"""BUG-4 regression: multiplex per-session path resolution.

In gateway.multiplex_profiles mode ONE default gateway process serves every
profile, and each profile keeps its own home/state.db/markers under
~/.hermes/profiles/<profile>/ (see user-guide/multi-profile-gateways.md). The
classifier's module-level path constants are import-time snapshots of the
PROCESS env, so without per-session resolution every profile's
markers/sentinels land in the DEFAULT home and the per-profile cron never sees
them.

Phase 59 (D-18, paths-for-session-regex-may-never-match): these tests
originally seeded an `agent:<profile>:…`-shaped session id and relied on
`_paths_for_session` parsing the profile out of the id itself. That regex
(`_NS_RE`) was a session-KEY-shaped pattern applied to a session ID and, per
the live capture that root-caused the fix, could never match a real session
id -- resolution was correct but INERT on the diagnosis host. Profile
resolution now reads `sessions.profile_name` from a real session ROW instead
(see tests/test_phase59_profile_resolution.py for the full proof); the tests
below are updated to seed that row rather than relying on a hand-built
identifier, while preserving exactly what each one was originally pinning:
the redirect, the default/absent-profile fail-open, and the nesting guard.

These tests pin: (1) _paths_for_session redirects a session whose row's
profile_name names an existing profile home, and falls back to the module
paths otherwise (default profile, no profile_name, or profile home absent —
the one-process-per-profile case); (2) a marker written for such a session
lands under the OWNING profile's markers dir, not the default home's.
"""
import importlib
import os
import shutil
import sqlite3
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

    def _seed_profile_name(self, db_path, session_id, profile_name):
        """Seed a minimal sessions row carrying `profile_name` at
        `db_path`, creating the table if needed. Phase 59 (D-18): profile
        resolution now reads this column from the session ROW rather than
        parsing an `agent:<profile>:` prefix off the session id, so these
        tests must seed a real row rather than relying on a hand-built
        namespaced identifier."""
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (id TEXT, profile_name TEXT)"
        )
        conn.execute(
            "INSERT INTO sessions (id, profile_name) VALUES (?, ?)",
            (session_id, profile_name),
        )
        conn.commit()
        conn.close()

    def test_namespaced_session_redirects_to_profile_home(self):
        # Phase 59 (D-18, paths-for-session-regex-may-never-match):
        # updated to seed a row instead of relying on an
        # `agent:<profile>:`-shaped identifier -- the original pin (a
        # session redirects to its owning profile's dirs) is unchanged.
        sid = "sess-1"
        self._seed_profile_name(os.path.join(self.dh, "state.db"), sid, "gtm")
        p = self.classifier._paths_for_session(sid)
        self.assertEqual(
            Path(p.markers_dir),
            Path(self.gtm) / "state" / "revenium" / "markers",
            "row-carried profile_name did not resolve to the owning profile's markers dir",
        )
        self.assertEqual(Path(p.state_db), Path(self.gtm) / "state.db")
        self.assertEqual(
            Path(p.markers_ready_dir),
            Path(self.gtm) / "state" / "revenium" / "markers" / ".ready",
        )

    def test_default_and_plain_sessions_use_module_paths(self):
        # Phase 59 (D-18): "default" now arrives as a row value, and the
        # literal "main" (session.py:1086's actual default-slot spelling,
        # the second latent mismatch this phase fixes) is covered
        # alongside it -- both mean the process-level home.
        mod = self.classifier._module_paths()
        db_path = os.path.join(self.dh, "state.db")
        self._seed_profile_name(db_path, "sess-default", "default")
        self._seed_profile_name(db_path, "sess-main", "main")
        for sid in ("plain-session-id", "sess-default", "sess-main"):
            p = self.classifier._paths_for_session(sid)
            self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir),
                             f"{sid} should resolve to the module (default) paths")

    def test_absent_profile_home_falls_back_to_module_paths(self):
        # One-process-per-profile mode: row names a profile with no
        # profiles/<x>/ under this process's home -> use the module paths
        # (process home is already right). Phase 59 (D-18): the profile
        # name now arrives via a seeded row, not a namespaced id.
        mod = self.classifier._module_paths()
        sid = "sess-nohome"
        self._seed_profile_name(os.path.join(self.dh, "state.db"), sid, "doesnotexist")
        p = self.classifier._paths_for_session(sid)
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_marker_lands_in_owning_profile_dir(self):
        # Phase 59 (D-18): the nesting guard and the marker-routing proof
        # now start from a row-carried profile_name.
        sid = "sess-42"
        self._seed_profile_name(os.path.join(self.dh, "state.db"), sid, "gtm")
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
