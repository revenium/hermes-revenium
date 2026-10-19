"""A subagent's completion waits for its root's job marker (subagent job-link leak).

Root cause (2026-10-18, ent profile): the job id a child session ships with is
resolved at SHIP time from its ROOT's marker file. The root's job marker is
written when the root's own turn completes, but a subagent is classified, and
gets its `.ready` sentinel, when ITS turn ends, which is well before. A child
that went ready first was visited with an empty root job id: the RC-2 gate (wait
for the root's `jobs create`) only runs when the root already has a job marker,
so the completion shipped with no `--agentic-job-id`, and a shipped transaction
cannot be linked to a job afterwards (the CLI has no such verb, and linking to a
job that is not live is a create). Since 2026-10-10, 82% of the subagent tokens
on ent shipped that way; Revenium job cost omitted most delegated work and job
ROI was inflated.

The G-03 filter now holds a child that would otherwise ship while its ROOT is
still LIVE, has no sentinel and no job record, is younger than
REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS, and a healthy classifier is registered.

Pinned here:
  * the leak itself (held, then shipped linked once the root's job exists, with
    `jobs create` ahead of every reference to the id, and idempotent after);
  * a pair marker on the root does NOT release the child (the pair can land
    twenty minutes before the job on a long root);
  * every bound (sentinel, idle root, ended root, cap, switch off, no plugin,
    older Hermes without parent_session_id) degrades to today's behaviour;
  * a root that already has a job record is the RC-2 gate's business, not this
    hold's, in the OWNING profile's markers directory;
  * one log line per held root, however many children it has.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    SCRIPTS_DIR,
    argv_to_flags,
    build_shim,
    build_state_db,
    run_script,
    seed_parent_session_ids,
)

ROOT = "sub-hold-root-0001"
KID = "sub-hold-kid-0001"
KID2 = "sub-hold-kid-0002"
KID3 = "sub-hold-kid-0003"
GRAND = "sub-hold-grand-0001"
JOB_ID = "reconcile_slack_gmail_todos_ab12"
SETTLE = 600
CAP_ENV = "REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS"


class SubagentJobLinkHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-subagent-link-hold-")
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
            "REVENIUM_CRON_SETTLE_SECONDS": str(SETTLE),
            "TZ": "UTC",
        }
        for k in ("METER_LOG", "JOBS_LOG", "TOOL_LOG", CAP_ENV):
            self.env.pop(k, None)
        self.now = time.time()
        self._seen = 0

    # --- fixture helpers -------------------------------------------------

    def _session(self, sid, *, source, started_ago, ended_ago=None, tokens=(1000, 500)):
        return {
            "id": sid, "model": "claude-sonnet-4-6", "source": source,
            "input_tokens": tokens[0], "output_tokens": tokens[1],
            "cache_read": 0, "cache_write": 0, "reasoning": 0,
            "estimated_cost": "0", "api_calls": 2,
            "started_at": self.now - started_ago,
            "ended_at": None if ended_ago is None else self.now - ended_ago,
            "billing_provider": "anthropic",
        }

    def _seed(self, *, root_started_ago=1800, root_active_ago=20, root_ended_ago=None,
              kids=(KID,), parents=None, parent_column=True, extra=()):
        """A live cron root and N finished subagent children. The root's
        last_activity_at is stamped (Hermes does so mid-turn)."""
        sessions = [self._session(ROOT, source="cron", started_ago=root_started_ago,
                                  ended_ago=root_ended_ago)]
        mapping = {ROOT: None}
        for i, kid in enumerate(kids):
            sessions.append(self._session(kid, source="subagent",
                                          started_ago=root_started_ago - 100 - i,
                                          ended_ago=600, tokens=(2000 + i, 1000)))
            mapping[kid] = ROOT
        for sess in extra:
            sessions.append(sess)
        if parents:
            mapping.update(parents)
        build_state_db(self.db, sessions)
        if parent_column:
            seed_parent_session_ids(self.db, mapping)
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN last_activity_at REAL")
            conn.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                         (None if root_active_ago is None else self.now - root_active_ago, ROOT))
            conn.commit()
        finally:
            conn.close()

    def _plugin_status(self, *, registered=True, healthy=True):
        Path(self.sd, "plugin-status.json").write_text(json.dumps({
            "healthy": healthy, "registered": registered, "liveness": "idle",
            "lastChecked": "2026-10-18T00:00:00Z",
        }))

    def _kid_ready(self, kid=KID, root=ROOT, markers_dir=None, ready_dir=None):
        """The child finished its own turn: pair marker plus sentinel."""
        d = markers_dir or self.md
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{kid}.jsonl"), "w") as f:
            f.write(json.dumps({
                "muid": f"kidmuid-{kid}", "ts": self.now - 590, "sid": kid,
                "task_type": "action_item_reconciliation", "operation_type": "CHAT",
                "trace_id": root,
            }, separators=(",", ":")) + "\n")
        rd = ready_dir or self.mrd
        os.makedirs(rd, exist_ok=True)
        Path(rd, kid).touch()

    def _root_markers(self, *, pair_ago=None, job_ago=None, markers_dir=None, sid=ROOT):
        d = markers_dir or self.md
        os.makedirs(d, exist_ok=True)
        recs = []
        if pair_ago is not None:
            for op in ("GUARDRAIL", "CHAT"):
                recs.append({
                    "muid": f"{op.lower()}-root-{int(pair_ago)}", "ts": self.now - pair_ago,
                    "sid": sid, "task_type": "action_item_reconciliation",
                    "operation_type": op, "trace_id": sid,
                })
        if job_ago is not None:
            recs.append({
                "kind": "job", "ts": self.now - job_ago, "sid": sid,
                "agentic_job_id": JOB_ID, "job_name": "Reconcile todos",
                "job_type": "action_item_reconciliation", "status": "SUCCESS",
            })
        with open(os.path.join(d, f"{sid}.jsonl"), "w") as f:
            for r in recs:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def _created(self, job_id=JOB_ID):
        with open(os.path.join(self.sd, "revenium-jobs.ledger"), "a") as f:
            f.write(f"JOB:{job_id}:created:{self.now - 30:.3f}\n")

    def _tick(self):
        rc, invocations, out = run_script(
            SCRIPTS_DIR / "hermes-report.sh", self.env, self.inv_log)
        self.assertEqual(rc, 0, f"hermes-report.sh failed: {out}")
        new = invocations[self._seen:]
        self._seen = len(invocations)
        self.last_all = invocations
        return new, out

    @staticmethod
    def _is(argv, verb, sub):
        return len(argv) >= 2 and argv[0] == verb and argv[1] == sub

    def _completions_for(self, invocations, sid):
        out = []
        for a in invocations:
            if self._is(a, "meter", "completion"):
                tx = argv_to_flags(a).get("--transaction-id", "")
                if isinstance(tx, str) and tx.startswith(f"{sid}-"):
                    out.append(a)
        return out

    def _read(self, path):
        if not os.path.exists(path):
            return ""
        with open(path) as fh:
            return fh.read()

    def _ledger(self):
        return self._read(os.path.join(self.sd, "revenium-hermes.ledger"))

    def _cron_log(self):
        return self._read(os.path.join(self.sd, "revenium-metering.log"))

    def _assert_kid_held(self, new, why, kid=KID):
        self.assertEqual(self._completions_for(new, kid), [], f"{why}: the child shipped.\n{new}")
        self.assertNotIn(f"HERMES:{kid}:", self._ledger(), f"{why}: the child was ledgered")

    def _assert_kid_shipped_unlinked(self, new, why, kid=KID):
        shipped = self._completions_for(new, kid)
        self.assertEqual(len(shipped), 1, f"{why}: expected one completion.\n{new}")
        self.assertNotIn("--agentic-job-id", shipped[0], why)

    def _assert_create_precedes_every_reference(self, invocations):
        create_idx = ref_idx = None
        for i, a in enumerate(invocations):
            flags = argv_to_flags(a)
            if self._is(a, "jobs", "create") and flags.get("--agentic-job-id") == JOB_ID and create_idx is None:
                create_idx = i
            if self._is(a, "meter", "completion") and flags.get("--agentic-job-id") == JOB_ID and ref_idx is None:
                ref_idx = i
        if ref_idx is None:
            return
        self.assertIsNotNone(create_idx, "a completion referenced the job but `jobs create` never ran")
        self.assertLess(create_idx, ref_idx, "a completion referenced the job BEFORE its create")

    # --- the leak --------------------------------------------------------

    def test_child_waits_for_a_live_root_then_ships_linked_after_the_create(self):
        """The reported defect. The subagent finished (pair marker + sentinel)
        while its root's turn is still running and has no job marker. It must
        not ship unlinked; once the root's job exists it ships WITH the link,
        after `jobs create`, exactly once."""
        self._seed()
        self._plugin_status()
        self._kid_ready()

        new, out = self._tick()
        self._assert_kid_held(new, "tick 1: root still running, job not written")
        self.assertIn(f"holding 1 subagent session(s) of {ROOT}", self._cron_log())

        # The root's turn ends: pair, then the job marker, then the boundary.
        self._root_markers(pair_ago=14, job_ago=4)
        Path(self.mrd, ROOT).touch()
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (self.now - 3, ROOT))
        conn.commit()
        conn.close()

        # Tick 2: the root's iteration creates the job; the child is still
        # waiting for that create (RC-2), so it has not shipped yet.
        new, out = self._tick()
        creates = [a for a in new if self._is(a, "jobs", "create")]
        self.assertEqual(len(creates), 1, new)
        self._assert_kid_held(new, "tick 2: create not ledgered when the child is visited")

        # Tick 3: the create is ledgered, the child ships linked.
        new, out = self._tick()
        shipped = self._completions_for(new, KID)
        self.assertEqual(len(shipped), 1, new)
        flags = argv_to_flags(shipped[0])
        self.assertEqual(flags.get("--agentic-job-id"), JOB_ID)
        self.assertEqual(flags.get("--input-tokens"), "2000")
        self.assertEqual(flags.get("--output-tokens"), "1000")
        self._assert_create_precedes_every_reference(self.last_all)

        # Tick 4: idempotent.
        new, out = self._tick()
        self.assertEqual(self._completions_for(new, KID), [], new)

    def test_without_the_hold_the_child_ships_unlinked(self):
        """Control: the same fixture with the hold switched off ships the child
        at once with no job link, which is the defect. It also proves the
        assertions above are not vacuous."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        self.env[CAP_ENV] = "0"
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "hold switched off")

    def test_a_pair_marker_alone_does_not_release_the_child(self):
        """The root's pair landed 11 minutes ago and the job inference has not
        produced a job yet (the measured 20-minute case): the root is still
        running, so the child keeps waiting."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        self._root_markers(pair_ago=SETTLE + 100)
        new, out = self._tick()
        self._assert_kid_held(new, "root has a pair but no job and is still live")
        self.assertIn(f"holding 1 subagent session(s) of {ROOT}", self._cron_log())

    def test_three_children_of_one_root_log_one_line_per_tick(self):
        self._seed(kids=(KID, KID2, KID3))
        self._plugin_status()
        for kid in (KID, KID2, KID3):
            self._kid_ready(kid)
        new, out = self._tick()
        for kid in (KID, KID2, KID3):
            self._assert_kid_held(new, "three children, one root", kid=kid)
        lines = [l for l in self._cron_log().splitlines() if "subagent session(s) of" in l]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(f"holding 3 subagent session(s) of {ROOT}", lines[0])

    def test_a_child_with_nothing_new_to_ship_is_not_held_or_counted(self):
        """The child's current total (2000+1000) is already ledgered: the
        per-session loop would skip it anyway, so it passes through and is not
        logged as waiting."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        with open(os.path.join(self.sd, "revenium-hermes.ledger"), "w") as f:
            f.write(f"HERMES:{KID}:3000:{self.now - 300:.3f}:kidmuid-{KID}\n")
        new, out = self._tick()
        self.assertEqual(self._completions_for(new, KID), [], new)
        self.assertNotIn("subagent session(s) of", self._cron_log())

    def test_a_child_with_new_tokens_since_its_last_shipment_is_held(self):
        """Same child, ledgered at an OLDER total: the growth has nothing to
        link to yet, so it waits and is counted."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        with open(os.path.join(self.sd, "revenium-hermes.ledger"), "w") as f:
            f.write(f"HERMES:{KID}:1500:{self.now - 300:.3f}:kidmuid-{KID}\n")
        new, out = self._tick()
        self.assertEqual(self._completions_for(new, KID), [], new)
        self.assertIn(f"holding 1 subagent session(s) of {ROOT}", self._cron_log())

    def test_a_ledgered_total_that_merely_starts_with_the_childs_is_not_a_match(self):
        """The ledger needle ends in a colon: `...:30001:` is not `...:3000:`."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        with open(os.path.join(self.sd, "revenium-hermes.ledger"), "w") as f:
            f.write(f"HERMES:{KID}:30001:{self.now - 300:.3f}:kidmuid-{KID}\n")
        new, out = self._tick()
        self.assertIn(f"holding 1 subagent session(s) of {ROOT}", self._cron_log())

    def test_a_grandchild_waits_for_the_top_root(self):
        extra = [self._session(GRAND, source="subagent", started_ago=1500, ended_ago=600)]
        self._seed(extra=extra, parents={GRAND: KID})
        self._plugin_status()
        self._kid_ready(KID)
        self._kid_ready(GRAND)
        new, out = self._tick()
        self._assert_kid_held(new, "grandchild", kid=GRAND)
        self._assert_kid_held(new, "child", kid=KID)

    # --- the root's job is already decided -------------------------------

    def test_root_with_a_job_record_is_left_to_the_create_gate(self):
        """The root's job marker exists and its create is ledgered: nothing to
        wait for, the child ships linked at once and no hold is logged."""
        self._seed(root_ended_ago=100)
        self._plugin_status()
        self._kid_ready()
        self._root_markers(pair_ago=120, job_ago=110)
        Path(self.mrd, ROOT).touch()
        self._created()
        new, out = self._tick()
        shipped = self._completions_for(new, KID)
        self.assertEqual(len(shipped), 1, new)
        self.assertEqual(argv_to_flags(shipped[0]).get("--agentic-job-id"), JOB_ID)
        self.assertNotIn("subagent session(s) of", self._cron_log())

    def test_root_sentinel_releases_a_child_whose_root_has_no_job(self):
        """The plugin has finished with the root (session boundary) and wrote no
        job: none is coming, so the child ships unlinked rather than waiting."""
        self._seed()
        self._plugin_status()
        self._kid_ready()
        Path(self.mrd, ROOT).touch()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root finalised without a job")

    # --- every bound degrades to today's behaviour -----------------------

    def test_idle_root_releases_the_child(self):
        self._seed(root_active_ago=SETTLE + 100)
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root quiet for longer than the settle window")

    def test_ended_root_is_waited_for_one_settle_window_after_its_end(self):
        """on_session_end classifies at the boundary, so a root that ended 30s
        ago may still be writing its job marker."""
        self._seed(root_ended_ago=30, root_active_ago=1500)
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_held(new, "root ended 30s ago, classifier at the boundary")

    def test_ended_root_releases_the_child_after_the_window(self):
        self._seed(root_ended_ago=SETTLE + 100, root_active_ago=SETTLE + 110)
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root ended a settle window ago")

    def test_cap_bounds_the_wait(self):
        self._seed(root_started_ago=7200 + 600)
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root older than the default cap")

    def test_cap_is_configurable(self):
        self._seed(root_started_ago=1800)
        self._plugin_status()
        self._kid_ready()
        self.env[CAP_ENV] = "900"
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root older than REVENIUM_UNCLASSIFIED_MAX_HOLD_SECONDS=900")

    def test_malformed_cap_falls_back_to_the_default(self):
        self._seed()
        self._plugin_status()
        self._kid_ready()
        self.env[CAP_ENV] = "two hours"
        new, out = self._tick()
        self._assert_kid_held(new, "a malformed cap must not disable the hold")

    def test_unregistered_plugin_keeps_metering_only_timing(self):
        self._seed()
        self._plugin_status(registered=False, healthy=False)
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "plugin not registered")

    def test_absent_plugin_status_keeps_todays_timing(self):
        self._seed()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "no plugin-status.json")

    def test_older_hermes_without_parent_session_id_keeps_todays_timing(self):
        """No parent_session_id column: no row is recognised as a child, so
        there is nothing to wait for and nothing may break."""
        self._seed(parent_column=False)
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "state.db without parent_session_id")

    def test_a_root_row_that_cannot_be_found_releases_the_child(self):
        """The parent link points at a session with no row: nothing to wait
        for. The walk stops at the missing id, exactly like the root resolver."""
        self._seed(kids=(KID,), parents={KID: "no-such-root"})
        self._plugin_status()
        self._kid_ready()
        new, out = self._tick()
        self._assert_kid_shipped_unlinked(new, "root row missing")

    def test_a_top_level_session_is_untouched_by_the_hold(self):
        """A session that is its own root is never a 'child': the existing
        live-unclassified rule is its only gate, and with a pair inside the
        window it ships as before."""
        self._seed(kids=())
        self._plugin_status()
        # 1800s old, first classification 400s after its start: inside the
        # settle window, so the root-side hold has nothing to add.
        self._root_markers(pair_ago=1400)
        new, out = self._tick()
        self.assertEqual(len(self._completions_for(new, ROOT)), 1, new)
        self.assertNotIn("subagent session(s) of", self._cron_log())

    # --- multiplexed profiles --------------------------------------------

    def test_root_job_is_looked_up_in_the_owning_profiles_directory(self):
        """A namespaced root whose OWNING profile already holds its job marker
        is decided. Looking only in the process-level directory would call it
        job-less and hold the child until the root idles; control: with no job
        record anywhere the same child IS held."""
        root = "agent:gtm:root-1"
        kid = "agent:gtm:kid-1"
        gtm_md = os.path.join(self.hh, "profiles", "gtm", "state", "revenium", "markers")
        os.makedirs(os.path.join(gtm_md, ".ready"), exist_ok=True)
        sessions = [
            self._session(root, source="cron", started_ago=1800),
            self._session(kid, source="subagent", started_ago=1700, ended_ago=600),
        ]
        build_state_db(self.db, sessions)
        seed_parent_session_ids(self.db, {root: None, kid: root})
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE sessions ADD COLUMN last_activity_at REAL")
        conn.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?", (self.now - 20, root))
        conn.execute("ALTER TABLE sessions ADD COLUMN profile_name TEXT")
        conn.execute("UPDATE sessions SET profile_name = 'gtm'")
        conn.commit()
        conn.close()
        self._plugin_status()
        self._kid_ready(kid, root=root, markers_dir=gtm_md, ready_dir=os.path.join(gtm_md, ".ready"))
        self._root_markers(pair_ago=120, job_ago=110, markers_dir=gtm_md, sid=root)
        self._tick()
        self.assertNotIn(f"subagent session(s) of {root}", self._cron_log())

        # The first tick shipped the child; forget that so it has something
        # new to ship again, then take the root's job record away.
        for name in ("revenium-hermes.ledger", "revenium-jobs.ledger"):
            path = os.path.join(self.sd, name)
            if os.path.exists(path):
                os.remove(path)
        os.remove(os.path.join(gtm_md, f"{root}.jsonl"))
        self._tick()
        self.assertIn(f"holding 1 subagent session(s) of {root}", self._cron_log())


if __name__ == "__main__":
    unittest.main()
