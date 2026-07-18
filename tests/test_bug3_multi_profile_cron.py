"""BUG-3/BUG-7 regression: multi-profile cron fan-out + orphan reconciliation.

BUG-3: install-cron.sh keyed the crontab on ONE fixed marker and treated the
crontab as a single line, so a second per-profile install OVERWROTE the first —
only one profile ended up metered. The fix gives each profile a UNIQUE marker
(# hermes-revenium-metering-<profile>) and rebuilds the whole crontab in one
write, so profiles never clobber one another. Works for both deployment modes
(one-process-per-profile and the multiplexed single gateway).

BUG-7: a wiped ~/.hermes leaves the metering line behind pointing at a
now-missing cron.sh, failing every minute. install-cron.sh reconciles orphaned
hermes-revenium-metering* lines whose target script no longer exists;
uninstall-cron.sh removes every metering line.

crontab is stubbed to a file so the test never touches the real user crontab.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "revenium" / "scripts"


class TestBug3MultiProfileCron(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsd-bug3-fleet-")
        self.home = os.path.join(self.tmp, "home")
        self.hermes = os.path.join(self.home, ".hermes")
        # Two named profiles + the default home.
        for p in ("alpha", "beta"):
            os.makedirs(os.path.join(self.hermes, "profiles", p, "state", "revenium"),
                        exist_ok=True)
        self.bin = os.path.join(self.home, ".local", "bin")
        os.makedirs(self.bin, exist_ok=True)

        # crontab shim -> a plain file.
        self.cronfile = os.path.join(self.tmp, "crontab.txt")
        shim = os.path.join(self.bin, "crontab")
        with open(shim, "w") as f:
            f.write(
                "#!/usr/bin/env bash\n"
                'f="${CRONTAB_FILE}"\n'
                'case "${1:-}" in\n'
                '  -l) [[ -f "$f" ]] && cat "$f" || exit 1 ;;\n'
                '  -r) rm -f "$f" ;;\n'
                '  -)  cat > "$f" ;;\n'
                '  *)  exit 0 ;;\n'
                'esac\n'
            )
        os.chmod(shim, 0o755)

        self.env = {
            **os.environ,
            "HOME": self.home,
            "HERMES_HOME": self.hermes,
            "HERMES_DEFAULT_HOME": self.hermes,
            "CRONTAB_FILE": self.cronfile,
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, script, *args):
        return subprocess.run(
            ["bash", str(SCRIPTS / script), *args],
            env=self.env, capture_output=True, text=True, timeout=30,
        )

    def _crontab(self):
        return Path(self.cronfile).read_text() if os.path.exists(self.cronfile) else ""

    def _markers(self):
        return sorted(
            tok
            for line in self._crontab().splitlines()
            for tok in [line.split("# hermes-revenium-metering")[-1]]
            if "hermes-revenium-metering" in line
        )

    def test_all_profiles_installs_unique_markers(self):
        r = self._run("install-cron.sh", "--all-profiles")
        self.assertEqual(r.returncode, 0, r.stderr)
        ct = self._crontab()
        for marker in ("# hermes-revenium-metering-default",
                       "# hermes-revenium-metering-alpha",
                       "# hermes-revenium-metering-beta"):
            self.assertIn(marker, ct, f"missing {marker}\n{ct}")
        # Three distinct lines, each with its own HERMES_HOME.
        self.assertIn("profiles/alpha", ct)
        self.assertIn("profiles/beta", ct)
        self.assertIn("REVENIUM_AGENT_NAME=Hermes-alpha", ct)
        self.assertIn("REVENIUM_AGENT_NAME=Hermes-beta", ct)
        self.assertIn("REVENIUM_AGENT_NAME=Hermes ", ct)  # default profile

    def test_second_profile_install_does_not_clobber_first(self):
        # This is the core BUG-3 regression.
        self._run("install-cron.sh", "--profile", "alpha")
        self.assertIn("# hermes-revenium-metering-alpha", self._crontab())
        self.assertNotIn("# hermes-revenium-metering-beta", self._crontab())

        # Installing beta must NOT remove alpha's line.
        self._run("install-cron.sh", "--profile", "beta")
        ct = self._crontab()
        self.assertIn("# hermes-revenium-metering-alpha", ct,
                      "BUG-3 REGRESSION: second profile install clobbered the first")
        self.assertIn("# hermes-revenium-metering-beta", ct)
        # Exactly one line per profile (no duplicates on re-run).
        self.assertEqual(self._crontab().count("# hermes-revenium-metering-alpha"), 1)

    def test_reruning_a_profile_is_idempotent(self):
        self._run("install-cron.sh", "--profile", "alpha")
        self._run("install-cron.sh", "--profile", "alpha")
        self.assertEqual(self._crontab().count("# hermes-revenium-metering-alpha"), 1,
                         "re-running a profile install duplicated its line")

    def test_orphan_line_is_reconciled(self):
        # Seed an orphan metering line pointing at a missing cron.sh.
        orphan = ("* * * * * HERMES_HOME=/gone bash /gone/cron.sh "
                  ">> /gone/log 2>&1 # hermes-revenium-metering-ghost\n")
        Path(self.cronfile).write_text(orphan)
        r = self._run("install-cron.sh", "--profile", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        ct = self._crontab()
        self.assertNotIn("hermes-revenium-metering-ghost", ct,
                         "BUG-7: orphaned metering line was not reconciled")
        self.assertIn("# hermes-revenium-metering-alpha", ct)
        self.assertIn("Removing orphaned metering cron line", r.stdout)

    def test_uninstall_removes_all_profiles(self):
        self._run("install-cron.sh", "--all-profiles")
        self.assertIn("hermes-revenium-metering", self._crontab())
        r = self._run("uninstall-cron.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("hermes-revenium-metering", self._crontab(),
                         "uninstall left metering lines behind")

    def test_uninstall_preserves_foreign_lines(self):
        Path(self.cronfile).write_text("0 3 * * * /usr/bin/backup.sh # nightly-backup\n")
        self._run("install-cron.sh", "--all-profiles")
        self._run("uninstall-cron.sh")
        ct = self._crontab()
        self.assertIn("nightly-backup", ct, "uninstall removed a foreign crontab line")
        self.assertNotIn("hermes-revenium-metering", ct)


if __name__ == "__main__":
    unittest.main()
