"""Settle window vs. a first turn longer than the window (pre-marker leak).

Root cause (2026-10-18, ent profile): the G-03 sentinel-or-aged filter in
hermes-report.sh measured the settle fallback from `sessions.started_at`. The
window exists to give the classifier time to finish AFTER it fires (the pair
marker, then the slow job-inference call, then the job marker). The plugin
fires at the END of the first turn, so for a turn longer than
REVENIUM_CRON_SETTLE_SECONDS the session was already "aged out" while it was
still running: every tick shipped the growing delta markerless
(`unclassified-<ts>`, no --agentic-job-id), and only the delta after the
end-of-turn marker was linked. Measured on ent: 20.5% of tokens since the
classifier stabilised (53% for cron sessions) shipped before the session's
first marker; Revenium job ROI was inflated up to ~2.7 million percent.

The fix keeps holding a session that is still LIVE (open, or ended less than
the settle window ago) and has no classifier marker yet, for at most
REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS from its start, and only while a healthy
classifier plugin is registered. A classification that lands after the old
window had already closed is given the settle window to finish its job
inference (job marker or sentinel releases it sooner).

Pinned here:
  * the leak itself (held, then shipped linked in ONE completion once the
    markers land);
  * every bound (cap, idle, switch off, no plugin, column absent) degrades to
    today's behaviour, never to a stranded session;
  * an ordinary session (marker inside the window) is untouched;
  * the marker is looked up in the OWNING profile's directory.
"""
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    SCRIPTS_DIR,
    build_shim,
    build_state_db,
    run_script,
    seed_parent_session_ids,
)

SID = "live-long-turn-sid"
JOB_ID = "reconcile_long_turn_ab12"
SETTLE = 600
CAP_ENV = "REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS"


class SettleLiveUnclassifiedHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-settle-live-hold-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hh = os.path.join(self.tmp, "hh")
        self.sd = os.path.join(self.hh, "state", "revenium")
        self.md = os.path.join(self.sd, "markers")
        self.mrd = os.path.join(self.md, ".ready")
        shim_home = os.path.join(self.tmp, "home")
        bin_dir = os.path.join(shim_home, ".local", "bin")
        for d in (self.md, self.mrd, bin_dir):
            os.makedirs(d, exist_ok=True)
        self.db = os.path.join(self.hh, "state.db")
        build_shim(os.path.join(bin_dir, "revenium"))
        self.meter_log = os.path.join(self.tmp, "meter.log")
        self.jobs_log = os.path.join(self.tmp, "jobs.log")
        self.inv_log = os.path.join(self.tmp, "inv.log")
        self.env = {
            **os.environ,
            "HOME": shim_home,
            "HERMES_HOME": self.hh,
            "REVENIUM_STATE_DIR": self.sd,
            "REVENIUM_MARKERS_DIR": self.md,
            "REVENIUM_MARKERS_READY_DIR": self.mrd,
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
            "INVOCATIONS_LOG": self.inv_log,
            "METER_LOG": self.meter_log,
            "JOBS_LOG": self.jobs_log,
            "REVENIUM_CRON_SETTLE_SECONDS": str(SETTLE),
            "TZ": "UTC",
        }
        self.env.pop(CAP_ENV, None)
        self.now = time.time()

    # --- fixture helpers -------------------------------------------------

    def _seed(self, *, started_ago, ended_ago=None, activity_ago="absent",
              sid=SID, activity_col=True, profile=None):
        """One token-bearing root session. activity_ago: seconds, None (NULL),
        or "absent" (column not created at all, the older-Hermes arm)."""
        started = self.now - started_ago
        ended = None if ended_ago is None else self.now - ended_ago
        build_state_db(self.db, [{
            "id": sid, "model": "claude-sonnet-4-6", "source": "cron",
            "input_tokens": 1000, "output_tokens": 500,
            "cache_read": 0, "cache_write": 0, "reasoning": 0,
            "estimated_cost": "0", "api_calls": 3,
            "started_at": started, "ended_at": ended,
            "billing_provider": "anthropic",
        }])
        seed_parent_session_ids(self.db, {sid: None})
        conn = sqlite3.connect(self.db)
        try:
            if activity_col and activity_ago != "absent":
                conn.execute("ALTER TABLE sessions ADD COLUMN last_activity_at REAL")
                value = None if activity_ago is None else self.now - activity_ago
                conn.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?", (value, sid))
            if profile is not None:
                conn.execute("ALTER TABLE sessions ADD COLUMN profile_name TEXT")
                conn.execute("UPDATE sessions SET profile_name = ? WHERE id = ?", (profile, sid))
            conn.commit()
        finally:
            conn.close()

    def _plugin_status(self, *, registered=True, healthy=True, liveness="idle"):
        Path(self.sd, "plugin-status.json").write_text(json.dumps({
            "healthy": healthy, "registered": registered, "liveness": liveness,
            "lastChecked": "2026-10-18T00:00:00Z",
        }))

    def _markers(self, *, pair_ago, job_ago=None, sid=SID, markers_dir=None):
        d = markers_dir or self.md
        os.makedirs(d, exist_ok=True)
        recs = []
        for op in ("GUARDRAIL", "CHAT"):
            recs.append({
                "muid": f"{op.lower()}muid{int(pair_ago)}", "ts": self.now - pair_ago,
                "sid": sid, "task_type": "action_item_reconciliation",
                "operation_type": op, "trace_id": sid,
            })
        if job_ago is not None:
            recs.append({
                "kind": "job", "ts": self.now - job_ago, "sid": sid,
                "agentic_job_id": JOB_ID, "job_name": "Reconcile action items",
                "job_type": "action_item_reconciliation", "status": "SUCCESS",
            })
        with open(os.path.join(d, f"{sid}.jsonl"), "w") as f:
            for r in recs:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def _tick(self):
        for p in (self.meter_log, self.jobs_log, self.inv_log):
            if os.path.exists(p):
                os.remove(p)
        rc, _inv, out = run_script(SCRIPTS_DIR / "hermes-report.sh", self.env, self.inv_log)
        self.assertEqual(rc, 0, f"hermes-report.sh failed: {out}")
        return out

    def _shipped(self):
        text = self._read(self.meter_log)
        return [shlex.split(l) for l in text.splitlines() if l.strip()]

    @staticmethod
    def _flag(argv, name):
        return argv[argv.index(name) + 1] if name in argv else None

    @staticmethod
    def _read(path):
        if not os.path.exists(path):
            return ""
        with open(path) as fh:
            return fh.read()

    def _ledger(self):
        return self._read(os.path.join(self.sd, "revenium-hermes.ledger"))

    def _cron_log(self):
        return self._read(os.path.join(self.sd, "revenium-metering.log"))

    def _assert_held(self, out, why):
        self.assertEqual(self._shipped(), [], f"{why}: a completion shipped.\n{out}")
        self.assertNotIn(f"HERMES:{SID}:", self._ledger(), f"{why}: the session was ledgered")

    def _assert_shipped_markerless(self, out, why):
        shipped = self._shipped()
        self.assertEqual(len(shipped), 1, f"{why}: expected one completion.\n{out}")
        self.assertEqual(self._flag(shipped[0], "--task-type"), "unclassified", why)
        self.assertNotIn("--agentic-job-id", shipped[0], why)

    # --- the leak --------------------------------------------------------

    def test_long_first_turn_is_held_then_ships_linked_in_one_completion(self):
        """The reported defect. A cron session 30 minutes into one turn, active
        20s ago, no marker and no sentinel yet, must NOT be shipped markerless;
        once the end-of-turn markers land it ships once, linked to its job."""
        self._seed(started_ago=1800, activity_ago=20)
        self._plugin_status()

        out = self._tick()
        self._assert_held(out, "tick 1: live session, first turn still running")
        self.assertIn(f"holding {SID}", self._cron_log())
        self.assertIn("first classification", self._cron_log())

        # The turn ends: pair, then the job marker ~10s later (the measured gap),
        # then the session boundary. The classification landed after the old
        # window had closed, which is exactly the late case.
        self._markers(pair_ago=14, job_ago=4)
        out = self._tick()
        shipped = self._shipped()
        self.assertEqual(len(shipped), 1, f"tick 2 should ship the whole backlog once.\n{out}")
        argv = shipped[0]
        self.assertEqual(self._flag(argv, "--agentic-job-id"), JOB_ID)
        self.assertEqual(self._flag(argv, "--task-type"), "action_item_reconciliation")
        self.assertEqual(self._flag(argv, "--input-tokens"), "1000")
        self.assertEqual(self._flag(argv, "--output-tokens"), "500")
        self.assertNotIn("unclassified-", self._ledger())

    def test_late_marker_without_job_marker_waits_out_job_inference(self):
        """A marker landed 30s ago, after the old window had closed, and the job
        inference that follows it has not produced a marker yet: shipping now
        would orphan the whole backlog (the BUG-1 race, reached through the long
        turn instead of the short one)."""
        self._seed(started_ago=1800, activity_ago=10)
        self._plugin_status()
        self._markers(pair_ago=30)
        out = self._tick()
        self._assert_held(out, "marker landed 30s ago, job inference may be in flight")

    def test_late_marker_without_job_marker_ships_once_the_window_has_passed(self):
        """The same state a settle window later: no job marker is coming (a
        non-agentic session), so the task-typed rows ship."""
        self._seed(started_ago=2400, activity_ago=10)
        self._plugin_status()
        self._markers(pair_ago=SETTLE + 60)
        out = self._tick()
        shipped = self._shipped()
        self.assertEqual(len(shipped), 1, out)
        self.assertEqual(self._flag(shipped[0], "--task-type"), "action_item_reconciliation")
        self.assertNotIn("--agentic-job-id", shipped[0])

    def test_sentinel_always_releases(self):
        self._seed(started_ago=1800, activity_ago=10)
        self._plugin_status()
        Path(self.mrd, SID).touch()
        out = self._tick()
        self.assertEqual(len(self._shipped()), 1, out)

    # --- the ordinary session is untouched -------------------------------

    def test_marker_inside_the_window_keeps_todays_timing(self):
        """Marker landed 500s after start (inside the 600s window), the session
        is still open and active, no sentinel (a gateway session mid-chat). It
        ships on the age fallback exactly as before; the hold must not extend
        to a classified session."""
        self._seed(started_ago=900, activity_ago=5)
        self._plugin_status()
        self._markers(pair_ago=400)
        out = self._tick()
        shipped = self._shipped()
        self.assertEqual(len(shipped), 1, f"classified session was held.\n{out}")
        self.assertEqual(self._flag(shipped[0], "--task-type"), "action_item_reconciliation")

    # --- every bound degrades to today's behaviour -----------------------

    def test_cap_bounds_the_hold(self):
        self._seed(started_ago=7200 + 600, activity_ago=5)
        self._plugin_status()
        out = self._tick()
        self._assert_shipped_markerless(out, "session older than the default cap")

    def test_cap_is_configurable(self):
        self._seed(started_ago=1800, activity_ago=5)
        self._plugin_status()
        self.env[CAP_ENV] = "900"
        out = self._tick()
        self._assert_shipped_markerless(out, "session older than REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=900")

    def test_zero_switches_the_hold_off(self):
        self._seed(started_ago=1800, activity_ago=5)
        self._plugin_status()
        self.env[CAP_ENV] = "0"
        out = self._tick()
        self._assert_shipped_markerless(out, "hold switched off")

    def test_malformed_cap_falls_back_to_the_default(self):
        self._seed(started_ago=1800, activity_ago=5)
        self._plugin_status()
        self.env[CAP_ENV] = "two hours"
        out = self._tick()
        self._assert_held(out, "a malformed cap must not disable the hold")

    def test_idle_session_is_released(self):
        """No activity for longer than the settle window: the classifier is not
        coming (the turn is not running), so ship."""
        self._seed(started_ago=1800, activity_ago=SETTLE + 100)
        self._plugin_status()
        out = self._tick()
        self._assert_shipped_markerless(out, "idle session")

    def test_ended_session_is_held_for_the_settle_window_after_it_ends(self):
        """on_session_end / on_session_finalize classify at the boundary (an
        interrupted turn fires no post_llm_call), so an ended session gets the
        settle window measured from ITS END."""
        # The last heartbeat is long before the end (Hermes ends a session it
        # interrupted well after the last stamp), so only ended_at keeps it live.
        self._seed(started_ago=1800, ended_ago=30, activity_ago=1500)
        self._plugin_status()
        out = self._tick()
        self._assert_held(out, "session ended 30s ago, classifier at the boundary")

    def test_ended_session_ships_once_the_window_after_its_end_passes(self):
        self._seed(started_ago=2400, ended_ago=SETTLE + 100, activity_ago=SETTLE + 110)
        self._plugin_status()
        out = self._tick()
        self._assert_shipped_markerless(out, "session ended a settle window ago")

    def test_null_activity_falls_back_to_start(self):
        self._seed(started_ago=1800, activity_ago=None)
        self._plugin_status()
        out = self._tick()
        self._assert_shipped_markerless(out, "last_activity_at NULL")

    def test_missing_activity_column_falls_back_to_start(self):
        self._seed(started_ago=1800, activity_ago="absent")
        self._plugin_status()
        out = self._tick()
        self._assert_shipped_markerless(out, "no last_activity_at column (older Hermes)")

    def test_unregistered_plugin_keeps_metering_only_timing(self):
        """Nothing is going to classify the session, so there is nothing to wait
        for: a metering-only install keeps today's timing and budget visibility."""
        self._seed(started_ago=1800, activity_ago=5)
        self._plugin_status(registered=False, healthy=False)
        out = self._tick()
        self._assert_shipped_markerless(out, "plugin not registered")

    def test_stalled_plugin_keeps_todays_timing(self):
        self._seed(started_ago=1800, activity_ago=5)
        self._plugin_status(registered=True, healthy=False, liveness="stalled")
        out = self._tick()
        self._assert_shipped_markerless(out, "plugin registered but not firing")

    def test_absent_plugin_status_keeps_todays_timing(self):
        """No plugin-status.json (never ran): no evidence a classifier exists."""
        self._seed(started_ago=1800, activity_ago=5)
        out = self._tick()
        self._assert_shipped_markerless(out, "no plugin-status.json")

    # --- multiplexed profiles --------------------------------------------

    def test_marker_is_looked_up_in_the_owning_profiles_directory(self):
        """A namespaced session whose OWNING profile already holds its markers
        is classified; looking only in the process-level directory would call it
        unclassified and hold it forever (bounded only by the cap). The hold
        must not log for it."""
        sid = "agent:gtm:sess-1"
        self._seed(started_ago=1800, activity_ago=5, sid=sid, profile="gtm")
        self._plugin_status()
        gtm_md = os.path.join(self.hh, "profiles", "gtm", "state", "revenium", "markers")
        os.makedirs(os.path.join(gtm_md, ".ready"), exist_ok=True)
        self._markers(pair_ago=SETTLE + 60, sid=sid, markers_dir=gtm_md)
        self._tick()
        self.assertNotIn(f"holding {sid}", self._cron_log())

        # Control: with no marker anywhere the same session IS held, so the
        # assertion above is not vacuous.
        os.remove(os.path.join(gtm_md, f"{sid}.jsonl"))
        self._tick()
        self.assertIn(f"holding {sid}", self._cron_log())


if __name__ == "__main__":
    unittest.main()
