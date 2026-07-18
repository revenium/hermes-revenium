"""Behavioral tests for the idempotent dedup + label-bearing naming in
setup-guardrails.sh.

These drive the real script against a stub `revenium` binary. The stub is
placed at ``$HOME/.local/bin/revenium`` under a throwaway HOME so that the
script's own ``ensure_path`` (which prepends ``~/.local/bin`` last, i.e. ahead
of everything else) resolves it before any real ``revenium`` on the host.

Covered cases:
  A  zero existing same-scope rules    -> create, name is label-bearing
  B  one existing same-scope rule      -> adopt + rename, no create
  C  two existing same-scope rules     -> warn + adopt first, no create
  D  existing rule with mismatched scope -> create (matcher discriminates)
"""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "revenium" / "scripts" / "setup-guardrails.sh"

LABEL = "testlabel"
AGENT = "Hermes"
NEW_ID = "new-rule-id"

STUB = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    args = sys.argv[1:]
    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a") as fh:
            fh.write("\\t".join(args) + "\\n")

    def rules():
        p = os.environ.get("STUB_RULES_FILE")
        if p and os.path.exists(p):
            try:
                return json.load(open(p))
            except Exception:
                return []
        return []

    # capability probes (has_guardrails_cli)
    if args[:3] == ["guardrails", "budget-rules", "--help"]:
        sys.exit(0)
    if args[:2] == ["guardrails", "enforcement-events"] and "--help" in args:
        sys.exit(0)

    if args[:3] == ["guardrails", "budget-rules", "list"]:
        print(json.dumps(rules()))
        sys.exit(0)
    if args[:3] == ["guardrails", "budget-rules", "get"]:
        rid = args[3] if len(args) > 3 else ""
        name = ""
        for r in rules():
            if r.get("id") == rid:
                name = r.get("name", "")
                break
        print(json.dumps({"id": rid, "name": name}))
        sys.exit(0)
    if args[:3] == ["guardrails", "budget-rules", "create"]:
        print(json.dumps({"id": os.environ.get("STUB_NEW_ID", "new-rule-id")}))
        sys.exit(0)
    if args[:3] == ["guardrails", "budget-rules", "update"]:
        sys.exit(0)
    if args[:3] == ["guardrails", "budget-rules", "delete"]:
        sys.exit(0)

    sys.exit(0)
    """
)


def _rule(rid, name, period="MONTHLY", agent=AGENT, group_by="AGENT", op="IS"):
    return {
        "id": rid,
        "name": name,
        "windowType": period,
        "groupBy": group_by,
        "filters": [{"dimension": "AGENT", "operator": op, "value": agent}],
    }


@unittest.skipUnless(SCRIPT.exists(), "setup-guardrails.sh not found")
class SetupGuardrailsDedupTests(unittest.TestCase):
    def _run(self, rules_list, args=("--hard-limit", "100", "--period", "MONTHLY")):
        """Run setup-guardrails.sh in default mode against a stub revenium.

        Returns (CompletedProcess, config_dict, log_lines).
        """
        tmp = Path(tempfile.mkdtemp())
        try:
            home = tmp / "home"
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            hermes_home = tmp / "hermes"
            state_dir = hermes_home / "state" / "revenium"
            state_dir.mkdir(parents=True)

            # stub revenium at ~/.local/bin/revenium (ensure_path puts it first)
            stub_path = local_bin / "revenium"
            stub_path.write_text(STUB)
            stub_path.chmod(0o755)

            rules_file = tmp / "rules.json"
            rules_file.write_text(json.dumps(rules_list))
            log_file = tmp / "calls.log"

            env = {
                "HOME": str(home),
                "HERMES_HOME": str(hermes_home),
                "REVENIUM_STATE_DIR": str(state_dir),
                "REVENIUM_TEAM_ID": "test-team",
                "REVENIUM_BUDGET_LABEL": LABEL,
                "REVENIUM_AGENT_NAME": AGENT,
                "STUB_RULES_FILE": str(rules_file),
                "STUB_NEW_ID": NEW_ID,
                "STUB_LOG": str(log_file),
                # Base PATH so bash/python3 resolve; ensure_path augments + reorders.
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            }

            bash = shutil.which("bash") or "/bin/bash"
            proc = subprocess.run(
                [bash, str(SCRIPT), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )

            config_path = state_dir / "config.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            log_lines = (
                log_file.read_text().splitlines() if log_file.exists() else []
            )
            return proc, config, log_lines
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _calls(log_lines, verb):
        # verb is the 3rd token, e.g. "create" / "update" / "delete" / "list".
        out = []
        for line in log_lines:
            parts = line.split("\t")
            if parts[:2] == ["guardrails", "budget-rules"] and len(parts) > 2 and parts[2] == verb:
                out.append(parts)
            elif len(parts) > 2 and parts[0] == "guardrails" and parts[1] == "budget-rules" and parts[2] == verb:
                out.append(parts)
        return out

    def _assert_stub_was_used(self, log_lines):
        # If the real revenium had shadowed the stub, the log would be empty.
        self.assertTrue(log_lines, "stub revenium was never invoked — PATH shadowing?")

    def test_organization_name_flag_persists_to_config(self):
        # BUG-2 follow-up: --organization-name writes organizationName to config.json
        # in the NON-INTERACTIVE (default) path, alongside ruleIds.
        proc, config, log = self._run(
            [],
            args=("--hard-limit", "100", "--period", "MONTHLY",
                  "--organization-name", "tableforone"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stub_was_used(log)
        self.assertEqual(config.get("organizationName"), "tableforone",
                         f"organizationName not persisted; config={config}")
        self.assertTrue(config.get("ruleIds"), "ruleIds missing")

    def test_no_organization_name_leaves_field_absent(self):
        # Without the flag, organizationName is not written (default path unchanged).
        proc, config, log = self._run([])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("organizationName", config,
                         "organizationName written without the flag")

    def test_a_zero_existing_creates_with_label_bearing_name(self):
        proc, config, log = self._run([])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stub_was_used(log)
        creates = self._calls(log, "create")
        self.assertEqual(len(creates), 1, "expected exactly one create")
        # --name carries the label-bearing unique name
        argv = creates[0]
        self.assertIn("--name", argv)
        name = argv[argv.index("--name") + 1]
        self.assertEqual(name, f"Hermes Monthly Budget — {LABEL}")
        self.assertEqual(config.get("ruleIds"), [NEW_ID])

    def test_b_one_existing_adopts_and_renames_no_create(self):
        existing = _rule("existing-1", "Old Name")
        proc, config, log = self._run([existing])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stub_was_used(log)
        self.assertEqual(self._calls(log, "create"), [], "must NOT create when a match exists")
        self.assertEqual(config.get("ruleIds"), ["existing-1"])
        # best-effort rename to the desired label-bearing name
        updates = self._calls(log, "update")
        self.assertEqual(len(updates), 1, "expected a rename update")
        argv = updates[0]
        name = argv[argv.index("--name") + 1]
        self.assertEqual(name, f"Hermes Monthly Budget — {LABEL}")

    def test_c_two_existing_warns_and_adopts_first_no_create(self):
        rules_list = [_rule("existing-1", "Dup A"), _rule("existing-2", "Dup B")]
        proc, config, log = self._run(rules_list)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stub_was_used(log)
        self.assertEqual(self._calls(log, "create"), [], "must NOT create with multiple matches")
        self.assertEqual(config.get("ruleIds"), ["existing-1"], "adopt the first match")
        out = proc.stdout
        self.assertIn("Found 2 existing same-scope", out)
        self.assertIn("delete existing-1", out)
        self.assertIn("delete existing-2", out)
        # no auto-delete
        self.assertEqual(self._calls(log, "delete"), [], "must not auto-delete duplicates")

    def test_d_scope_mismatch_falls_through_to_create(self):
        # Existing rule is DAILY; desired is MONTHLY -> no match -> create.
        existing = _rule("daily-1", "Daily Rule", period="DAILY")
        proc, config, log = self._run([existing])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_stub_was_used(log)
        self.assertEqual(len(self._calls(log, "create")), 1, "mismatched scope must create")
        self.assertEqual(config.get("ruleIds"), [NEW_ID])


if __name__ == "__main__":
    unittest.main()
