"""Phase 59 Plan 04 (D-18, D-18a, D-19) -- proof that per-session profile
resolution now reads `sessions.profile_name` from a real session ROW, that
`classifier.py` and `resolve-markers-dir.py` agree at every one of those
rows, and that the revenue-attribution fence flips correctly on both sides
of its own boundary.

The folded todo this closes: `paths-for-session-regex-may-never-match`
(severity high, root-caused 2026-08-31, Hermes v0.20.1, from a live
capture on the diagnosis multiplex host). Its own filing names why unit
tests could not have caught the original defect:
`ProfileScopedBoundaryProvenanceTests` constructs `agent:`-shaped session
ids BY HAND, so it proves the paths-threading mechanism GIVEN a matching
id and can never prove that a real session actually produces one. Every
test in this module instead takes its input from a real session row's
`profile_name` column in a schema-faithful fixture database (D-19),
matching the captured shape: `profile_name` populated on `api_server`
rows, NULL on cli/cron/subagent rows, ids in the captured formats
(`20260831_162501_ccfdf5` for cli/cron/subagent, `api-1b852ab4523500e5`
for `api_server`).

D-20's scoping applies here as to every other Phase 59 folded-todo plan:
this plan advances neither SSE-04 nor SSE-05, and its deliberate
per-profile routing/pricing behaviour change must not be read as a
criterion-1/5 violation -- see 59-04-PLAN.md's own
`<requirements_scoping>`.

Two open questions the filing explicitly leaves open, and this module
does NOT close either of them: whether other Hermes versions mint session
ids from the same `agent:<profile>:` namespace this repo has now stopped
depending on for resolution, and whether `profile_name` is populated on
Telegram/Discord/Slack gateway sessions. Neither blocks this fix -- a
NULL `profile_name` fails open to today's behaviour either way -- and
neither is exercised by anything below.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import sqlite3
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

# Every path-override env var either side of the resolution consults, so a
# test in this module can never leak a redirect into another test module
# (mirrors tests/test_bug4_multiplex_paths.py's own snapshot set, widened
# by the config/job-assessments/event-spool overrides this module also
# touches).
_ENV_KEYS = (
    "HERMES_HOME", "REVENIUM_STATE_DIR", "REVENIUM_MARKERS_DIR",
    "REVENIUM_MARKERS_READY_DIR", "REVENIUM_TAXONOMY_FILE",
    "REVENIUM_JOB_TAXONOMY_FILE", "REVENIUM_CONFIG_FILE",
    "REVENIUM_JOB_ASSESSMENTS_DIR", "REVENIUM_EVENT_SPOOL_DIR",
)


def build_state_db_with_profile_name(path, sessions):
    """Create a Hermes sessions DB at `path` matching the CAPTURED shape
    from the diagnosis host: the production schema (identical to
    tests/_compat_helpers.py's `build_state_db`) PLUS a `profile_name
    TEXT` column.

    Deliberately local, NOT an edit to tests/_compat_helpers.py:
    `build_state_db`'s schema -- no `profile_name` column at all -- IS the
    backward-compatibility arm this plan's fix must degrade to, and it
    must stay exactly as it is for that arm to mean anything.

    Each session dict provides `id`, and MAY provide `source` and
    `profile_name`; every other production column is filled with an inert
    default -- this module's tests only ever read `profile_name` off the
    row, never the metering columns.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        'CREATE TABLE sessions ('
        'id TEXT, model TEXT, source TEXT, '
        'input_tokens INTEGER, output_tokens INTEGER, '
        'cache_read_tokens INTEGER, cache_write_tokens INTEGER, '
        'reasoning_tokens INTEGER, estimated_cost_usd TEXT, '
        'api_call_count INTEGER, started_at REAL, ended_at REAL, '
        'billing_provider TEXT, profile_name TEXT)'
    )
    for s in sessions:
        conn.execute(
            'INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                s['id'], s.get('model', 'claude-sonnet-4'),
                s.get('source', 'cli'),
                s.get('input_tokens', 0), s.get('output_tokens', 0),
                s.get('cache_read', 0), s.get('cache_write', 0),
                s.get('reasoning', 0), s.get('estimated_cost', '0.0'),
                s.get('api_calls', 1), s.get('started_at', 0.0),
                s.get('ended_at', 0.0), s.get('billing_provider', 'anthropic'),
                s.get('profile_name'),
            ),
        )
    conn.commit()
    conn.close()


def _load_sidecar():
    """Load resolve-markers-dir.py as an importable module (hyphenated
    filename forbids `import` syntax -- same technique
    tests/test_phase28_multiplex_trace.py and tests/test_repository.py use
    for the same reason)."""
    spec = importlib.util.spec_from_file_location(
        "phase59_resolve_markers_dir", str(SIDECAR),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _ProfileResolutionFixtureCase(unittest.TestCase):
    """Shared harness: a temp HERMES_HOME, an env snapshot/restore, the
    plugin directory pushed onto sys.path, and the classifier reloaded
    against the temp env. Mirrors tests/test_bug4_multiplex_paths.py's
    setUp/tearDown."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-phase59-profile-resolution-")
        self.hh = os.path.join(self.tmp, ".hermes")
        os.makedirs(
            os.path.join(self.hh, "state", "revenium", "markers", ".ready"),
            exist_ok=True,
        )

        self._snapshot = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["HERMES_HOME"] = self.hh
        for k in _ENV_KEYS:
            if k != "HERMES_HOME":
                os.environ.pop(k, None)

        self._path_added = str(PLUGIN_DIR) not in sys.path
        if self._path_added:
            sys.path.insert(0, str(PLUGIN_DIR))
        import classifier
        self.classifier = importlib.reload(classifier)
        self.sidecar = _load_sidecar()

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

    # -- shared fixture helpers ------------------------------------------

    def _root_db(self):
        return os.path.join(self.hh, "state.db")

    def _make_profile_home(self, name):
        home = os.path.join(self.hh, "profiles", name)
        os.makedirs(
            os.path.join(home, "state", "revenium", "markers", ".ready"),
            exist_ok=True,
        )
        return home

    def _seed_root(self, sessions):
        build_state_db_with_profile_name(self._root_db(), sessions)

    def _seed_profile_db(self, profile_name, sessions):
        home = os.path.join(self.hh, "profiles", profile_name)
        os.makedirs(home, exist_ok=True)
        build_state_db_with_profile_name(
            os.path.join(home, "state.db"), sessions,
        )


class RowBasedResolutionTests(_ProfileResolutionFixtureCase):
    """Task 2's <behavior> list, classifier side, each driven from a real
    session row rather than a hand-built identifier."""

    def test_row_resolved_profile_with_existing_home_returns_profile_paths(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "api-1b852ab4523500e5", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        p = self.classifier._paths_for_session("api-1b852ab4523500e5")
        profile_home = Path(self.hh) / "profiles" / "p52alpha"
        state_dir = profile_home / "state" / "revenium"
        self.assertEqual(Path(p.markers_dir), state_dir / "markers")
        self.assertEqual(Path(p.taxonomy_file), state_dir / "task-taxonomy.json")
        self.assertEqual(Path(p.job_taxonomy_file), state_dir / "job-taxonomy.json")
        self.assertEqual(Path(p.guardrail_status_file), state_dir / "guardrail-status.json")
        self.assertEqual(Path(p.config_file), state_dir / "config.json")
        self.assertEqual(Path(p.state_db), profile_home / "state.db")
        self.assertEqual(Path(p.job_assessments_dir), state_dir / "job-assessments")

    def test_profile_home_only_db_engages_via_scan(self):
        # The captured host's actual shape: the row lives in the PROFILE's
        # own database, NOT the root -- option-b's whole reason for being
        # (Task 1 checkpoint). The root db has ITS OWN unrelated rows but
        # nothing for this session id, so resolution must fall through to
        # the bounded profile-home scan rather than stopping at the root.
        self._make_profile_home("p52alpha")
        self._seed_profile_db("p52alpha", [{
            "id": "api-1b852ab4523500e5", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        self._seed_root([{
            "id": "20260831_162501_ccfdf5", "source": "cli",
            "profile_name": None,
        }])
        p = self.classifier._paths_for_session("api-1b852ab4523500e5")
        profile_home = Path(self.hh) / "profiles" / "p52alpha"
        self.assertEqual(Path(p.markers_dir), profile_home / "state" / "revenium" / "markers")

    def test_row_resolved_profile_with_absent_home_falls_open(self):
        self._seed_root([{
            "id": "api-noHome", "source": "api_server",
            "profile_name": "p52beta",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("api-noHome")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_null_profile_name_falls_open(self):
        self._seed_root([{
            "id": "20260831_162501_ccfdf5", "source": "cli",
            "profile_name": None,
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("20260831_162501_ccfdf5")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_traversal_shaped_profile_value_falls_open(self):
        # The value arrives from a session ROW now, not from the id --
        # the directory-existence check must still refuse it.
        self._seed_root([{
            "id": "sess-traversal", "source": "api_server",
            "profile_name": "../../etc",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-traversal")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_no_sessions_table_falls_open_without_raising(self):
        conn = sqlite3.connect(self._root_db())
        conn.execute("CREATE TABLE other (id TEXT)")
        conn.commit()
        conn.close()
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("anything")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_missing_db_file_falls_open_without_raising(self):
        # No state.db at all, no profiles/ directory either.
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("anything")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_locked_db_never_raises(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "sess-lock", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        lock_conn = sqlite3.connect(self._root_db())
        lock_conn.execute("BEGIN EXCLUSIVE")
        lock_conn.execute("CREATE TABLE IF NOT EXISTS _lock_probe (x INTEGER)")
        try:
            # The load-bearing property is "no exception escapes" -- not a
            # specific resolved profile, since exclusive-lock visibility to
            # a read-only connection is platform/sqlite-build dependent.
            p = self.classifier._paths_for_session("sess-lock")
            self.assertIsNotNone(p)
        finally:
            lock_conn.rollback()
            lock_conn.close()

    def test_session_id_with_quote_and_semicolon_resolves_correctly(self):
        sid = "sess-'; DROP TABLE sessions;--"
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": sid, "source": "api_server", "profile_name": "p52alpha",
        }])
        p = self.classifier._paths_for_session(sid)
        profile_home = Path(self.hh) / "profiles" / "p52alpha"
        self.assertEqual(Path(p.markers_dir), profile_home / "state" / "revenium" / "markers")
        # The bound parameter, not interpolated text: the table survives.
        conn = sqlite3.connect(self._root_db())
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_resolution_never_writes_to_state_db(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "sess-ro", "source": "api_server", "profile_name": "p52alpha",
        }])
        before = Path(self._root_db()).read_bytes()
        self.classifier._paths_for_session("sess-ro")
        after = Path(self._root_db()).read_bytes()
        self.assertEqual(before, after, "resolution must never write to state.db")


class DefaultSlotTests(_ProfileResolutionFixtureCase):
    """`default`, `main`, empty, whitespace-only and NULL -- each
    resolving to the process-level paths."""

    def test_default_spelling_falls_open(self):
        self._seed_root([{
            "id": "sess-default", "source": "api_server",
            "profile_name": "default",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-default")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_main_spelling_falls_open(self):
        # session.py:1086 mints the literal "main" for the default
        # profile's slot -- the second latent mismatch Task 2 fixes at
        # the same call site as the row-based resolution itself.
        self._seed_root([{
            "id": "sess-main", "source": "api_server", "profile_name": "main",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-main")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_empty_string_falls_open(self):
        self._seed_root([{
            "id": "sess-empty", "source": "api_server", "profile_name": "",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-empty")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_whitespace_only_falls_open(self):
        self._seed_root([{
            "id": "sess-ws", "source": "api_server", "profile_name": "   ",
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-ws")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_null_falls_open(self):
        self._seed_root([{
            "id": "sess-null", "source": "cli", "profile_name": None,
        }])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("sess-null")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))


class BackwardCompatibilityTests(_ProfileResolutionFixtureCase):
    """A `sessions` table with no `profile_name` column at all is not
    hypothetical -- it is every existing fixture in this repo and every
    Hermes predating the column. This arm proves the missing column is a
    fail-open, not an exception, on BOTH implementations."""

    def _seed_legacy_root(self, sessions):
        # tests/_compat_helpers.py's build_state_db schema, verbatim --
        # deliberately NOT touched by this plan. This local copy proves
        # the same shape without importing across test modules.
        conn = sqlite3.connect(self._root_db())
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
                (s['id'], 'claude-sonnet-4', s.get('source', 'cli'),
                 0, 0, 0, 0, 0, '0.0', 1, 0.0, 0.0, 'anthropic'),
            )
        conn.commit()
        conn.close()

    def test_classifier_falls_open_with_no_profile_name_column(self):
        self._seed_legacy_root([{"id": "legacy-sess-1", "source": "cli"}])
        mod = self.classifier._module_paths()
        p = self.classifier._paths_for_session("legacy-sess-1")
        self.assertEqual(Path(p.markers_dir), Path(mod.markers_dir))

    def test_sidecar_falls_open_with_no_profile_name_column(self):
        self._seed_legacy_root([{"id": "legacy-sess-1", "source": "cli"}])
        module_dir = self.sidecar._module_state_subdir("markers")
        got = self.sidecar.resolve_state_subdir("legacy-sess-1", "markers")
        self.assertEqual(got, str(module_dir))


class ResolverParityTests(_ProfileResolutionFixtureCase):
    """The two implementations resolving differently is the cross-profile
    double-ship hazard this repo has already paid for once. This matrix
    drives BOTH the Python sidecar and the bash wrapper, so the shell path
    is covered and not only the Python one."""

    def _assert_parity(self, sid):
        classifier_paths = self.classifier._paths_for_session(sid)
        expectations = {
            "markers": classifier_paths.markers_dir,
            "api-events": classifier_paths.state_dir / "api-events",
            "job-assessments": classifier_paths.job_assessments_dir,
        }
        for subdir, classifier_dir in expectations.items():
            sidecar_dir = self.sidecar.resolve_state_subdir(sid, subdir)
            self.assertEqual(
                str(classifier_dir), sidecar_dir,
                f"resolver disagreement for sid={sid!r} subdir={subdir!r}: "
                f"classifier={classifier_dir!r} sidecar={sidecar_dir!r}",
            )

    def test_row_resolved_profile_parity(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "api-parity-1", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        self._assert_parity("api-parity-1")

    def test_null_profile_parity(self):
        self._seed_root([{
            "id": "cli-parity-1", "source": "cli", "profile_name": None,
        }])
        self._assert_parity("cli-parity-1")

    def test_main_profile_parity(self):
        self._seed_root([{
            "id": "sess-main-parity", "source": "api_server",
            "profile_name": "main",
        }])
        self._assert_parity("sess-main-parity")

    def test_nonexistent_profile_home_parity(self):
        self._seed_root([{
            "id": "sess-nohome-parity", "source": "api_server",
            "profile_name": "ghost",
        }])
        self._assert_parity("sess-nohome-parity")

    def test_traversal_shaped_profile_parity(self):
        self._seed_root([{
            "id": "sess-traversal-parity", "source": "api_server",
            "profile_name": "../../evil",
        }])
        self._assert_parity("sess-traversal-parity")

    def test_missing_column_parity(self):
        conn = sqlite3.connect(self._root_db())
        conn.execute("CREATE TABLE sessions (id TEXT, source TEXT)")
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?)",
            ("sess-nocol-parity", "cli"),
        )
        conn.commit()
        conn.close()
        self._assert_parity("sess-nocol-parity")

    def test_shell_wrapper_matches_python_sidecar(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "api-shell-parity", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        expected = self.sidecar.resolve_markers_dir("api-shell-parity")
        driver = os.path.join(self.tmp, "driver.sh")
        with open(driver, "w") as f:
            f.write(
                "#!/usr/bin/env bash\n"
                "set -uo pipefail\n"
                f'source "{COMMON_SH}"\n'
                'resolve_markers_dir "api-shell-parity"\n'
            )
        os.chmod(driver, 0o755)
        result = subprocess.run(
            ["bash", driver], capture_output=True, text=True,
            env=dict(os.environ), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), expected)


class RevenueFenceFlipTests(_ProfileResolutionFixtureCase):
    """D-18a: the fence has returned False on every multiplexed host since
    Phase 54; this repair is what flips it. Both sides, plus the
    consequence -- which config.json is actually read."""

    def test_fence_false_when_resolution_did_not_engage(self):
        self._make_profile_home("p52alpha")  # multiplexed (profiles/ has a subdir)
        # No row anywhere for this session -- resolution never engages.
        paths = self.classifier._paths_for_session("no-row-anywhere")
        self.assertFalse(
            self.classifier._revenue_profile_attribution_certain(paths))

    def test_fence_true_when_resolution_engages(self):
        self._make_profile_home("p52alpha")
        self._seed_root([{
            "id": "api-fence-engaged", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        paths = self.classifier._paths_for_session("api-fence-engaged")
        self.assertTrue(
            self.classifier._revenue_profile_attribution_certain(paths))

    def test_fence_true_with_no_profiles_directory(self):
        # Single-profile host -- no profiles/ directory at all.
        paths = self.classifier._paths_for_session("plain-sid")
        self.assertTrue(
            self.classifier._revenue_profile_attribution_certain(paths))

    def test_engaged_resolution_reads_the_profile_config_not_the_root(self):
        profile_home = self._make_profile_home("p52alpha")
        root_config = Path(self.hh) / "state" / "revenium" / "config.json"
        root_config.parent.mkdir(parents=True, exist_ok=True)
        root_config.write_text(
            '{"boundaries": {"valuation": "root_impl"}}', encoding="utf-8",
        )
        profile_config = Path(profile_home) / "state" / "revenium" / "config.json"
        profile_config.parent.mkdir(parents=True, exist_ok=True)
        profile_config.write_text(
            '{"boundaries": {"valuation": "profile_impl"}}', encoding="utf-8",
        )
        self._seed_root([{
            "id": "api-fence-config", "source": "api_server",
            "profile_name": "p52alpha",
        }])
        paths = self.classifier._paths_for_session("api-fence-config")
        self.assertTrue(
            self.classifier._revenue_profile_attribution_certain(paths))
        got = self.classifier._boundary_impl_name(
            "valuation", "hours_times_rate", paths=paths)
        self.assertEqual(got, "profile_impl")


if __name__ == "__main__":
    unittest.main()
