"""BUG-1 regression: slow job-inference must not orphan a session's completions.

Root cause (see references/setup.md "REVENIUM_CRON_SETTLE_SECONDS sizing"): the
classifier plugin writes fast task markers first, then does a SLOW LLM
job-inference call, then writes the kind:"job" marker AND the .ready sentinel.
The reporter gated on `has_sentinel OR age >= REVENIUM_CRON_SETTLE_SECONDS`. With
the old 45s default, under concurrent multi-profile load job-inference latency
(~200s observed) exceeded 45s, so the age-fallback metered + ledgered the
completions BEFORE the job marker existed. Per-muid dedup then permanently
orphaned them — the job, created a tick later, had zero transactions.

The fix makes the .ready sentinel the AUTHORITATIVE gate and raises the age
fallback default to 600s (must exceed worst-case job-inference latency). A
session with no sentinel and no job marker is DEFERRED until the sentinel lands
(which the plugin writes only AFTER the job marker), so completions and their
job marker are always read in the same tick.

This test simulates >60s of job-inference latency:
  Tick 1  — task markers written, NO job marker, NO sentinel, session aged 90s
            (older than the OLD 45s default, younger than the new 600s default).
            Assert: NOTHING metered, NOTHING ledgered (no orphaning).
  Tick 2  — plugin "finishes": append the job marker AND drop the sentinel.
            Assert: completions now ship WITH --agentic-job-id, and jobs create
            fired for that id — i.e. the completions associate with the job.
"""
import json
import os
import shlex
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import (
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

SID = "bug1-slow-job-sid"
JOB_ID = "bug1_fix_auth_regression_ab12"


class TestBug1SlowJobInference(unittest.TestCase):
    def _env(self, tmp):
        hh = os.path.join(tmp, "hh")
        sd = os.path.join(hh, "state", "revenium")
        md = os.path.join(sd, "markers")
        mrd = os.path.join(md, ".ready")
        shim_home = os.path.join(tmp, "home")
        bin_dir = os.path.join(shim_home, ".local", "bin")
        for d in (md, mrd, bin_dir):
            os.makedirs(d, exist_ok=True)

        state_db = os.path.join(hh, "state.db")
        # Aged 90s: under the OLD 45s default this would age-fallback and orphan.
        started = time.time() - 90
        build_state_db(state_db, [{
            "id": SID, "model": "claude-sonnet-4-6", "source": "cli",
            "input_tokens": 1000, "output_tokens": 500,
            "cache_read": 0, "cache_write": 0, "reasoning": 0,
            "estimated_cost": "0", "api_calls": 1,
            "started_at": started, "ended_at": started, "billing_provider": "anthropic",
        }])

        shim = os.path.join(bin_dir, "revenium")
        build_shim(shim)

        meter_log = os.path.join(tmp, "meter.log")
        jobs_log = os.path.join(tmp, "jobs.log")
        inv_log = os.path.join(tmp, "inv.log")

        env = {
            **os.environ,
            "HOME": shim_home,
            "HERMES_HOME": hh,
            "REVENIUM_STATE_DIR": sd,
            "REVENIUM_MARKERS_DIR": md,
            "REVENIUM_MARKERS_READY_DIR": mrd,
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
            "INVOCATIONS_LOG": inv_log,
            "METER_LOG": meter_log,
            "JOBS_LOG": jobs_log,
            "TZ": "UTC",
            # Deliberately DO NOT set REVENIUM_CRON_SETTLE_SECONDS — exercise the
            # shipped default (600s) so this test pins the fix, not a test knob.
        }
        return env, sd, md, mrd, meter_log, jobs_log, inv_log

    def _task_marker(self, ts):
        return {
            "muid": "bug1muid0001",
            "ts": ts,
            "sid": SID,
            "task_type": "fix_auth_regression",
            "operation_type": "CHAT",
        }

    def _job_marker(self, ts):
        return {
            "kind": "job",
            "ts": ts,
            "sid": SID,
            "agentic_job_id": JOB_ID,
            "job_name": "Fix auth regression",
            "job_type": "code_fix",
            "status": "SUCCESS",
        }

    def test_completions_deferred_until_job_marker_then_associate(self):
        tmp = tempfile.mkdtemp(prefix="gsd-bug1-slow-job-")
        try:
            env, sd, md, mrd, meter_log, jobs_log, inv_log = self._env(tmp)
            marker_path = os.path.join(md, f"{SID}.jsonl")
            ledger = os.path.join(sd, "revenium-hermes.ledger")

            # --- Tick 1: task marker only, no job marker, no sentinel. ---
            base = time.time() - 80
            with open(marker_path, "w") as f:
                f.write(json.dumps(self._task_marker(base), separators=(",", ":")) + "\n")

            rc, _inv, out = run_script(SCRIPTS_DIR / "hermes-report.sh", env, inv_log)
            self.assertEqual(rc, 0, f"tick 1 hermes-report.sh failed: {out}")

            meter_size = os.path.getsize(meter_log) if os.path.exists(meter_log) else 0
            self.assertEqual(
                meter_size, 0,
                "BUG-1 REGRESSION: completions were metered BEFORE the job marker "
                "existed (would permanently orphan them). meter.log:\n"
                + (open(meter_log).read() if meter_size else ""),
            )
            # The ledger must carry no HERMES row for this session yet — if it did,
            # per-muid dedup would orphan those muids forever.
            ledger_txt = open(ledger).read() if os.path.exists(ledger) else ""
            self.assertNotIn(
                f"HERMES:{SID}:", ledger_txt,
                "BUG-1 REGRESSION: completions were ledgered before the job marker",
            )
            # The reporter logs "deferred — awaiting plugin sentinels" to the cron
            # logfile (info() only mirrors to stderr under a TTY, not subprocess).
            cron_log_path = os.path.join(sd, "revenium-metering.log")
            cron_log = open(cron_log_path).read() if os.path.exists(cron_log_path) else ""
            self.assertIn("deferred", (out + cron_log).lower(),
                          "expected the session to be deferred awaiting the sentinel")

            # --- The classifier plugin "finishes" its slow job inference: the job
            # marker is appended AFTER the task markers, THEN the sentinel drops. ---
            with open(marker_path, "a") as f:
                f.write(json.dumps(self._job_marker(base + 1), separators=(",", ":")) + "\n")
            Path(os.path.join(mrd, SID)).touch()

            # --- Tick 2: sentinel present -> session ships; completions attach. ---
            rc, _inv, out = run_script(SCRIPTS_DIR / "hermes-report.sh", env, inv_log)
            self.assertEqual(rc, 0, f"tick 2 hermes-report.sh failed: {out}")

            self.assertTrue(
                os.path.exists(meter_log) and os.path.getsize(meter_log) > 0,
                f"tick 2: completions were not metered after the sentinel landed.\n{out}",
            )
            meter_argv = [
                shlex.split(line)
                for line in open(meter_log).read().splitlines() if line.strip()
            ]
            # Every metered completion for this session must carry the job id.
            self.assertTrue(meter_argv, "no meter completion argv captured on tick 2")
            for argv in meter_argv:
                self.assertIn(
                    "--agentic-job-id", argv,
                    f"completion shipped WITHOUT --agentic-job-id (orphaned): {argv}",
                )
                idx = argv.index("--agentic-job-id")
                self.assertEqual(
                    argv[idx + 1], JOB_ID,
                    f"completion associated to the wrong job id: {argv}",
                )

            # jobs create must have fired for this id (so the job exists to attach to).
            jobs_txt = open(jobs_log).read() if os.path.exists(jobs_log) else ""
            self.assertIn("jobs create", jobs_txt, "jobs create never fired on tick 2")
            self.assertIn(JOB_ID, jobs_txt, "jobs create did not reference the job id")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
