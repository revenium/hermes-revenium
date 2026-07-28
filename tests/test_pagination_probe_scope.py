"""Source-level invariant: every `--page` capability probe gates only the CLI
verb it actually probed.

`--page` is per-command surface, not a global property of the `revenium` CLI.
Deriving one verb's pagination support from another's makes correctness depend
on two unrelated command surfaces advertising and interpreting the flag
identically, in every CLI version, forever. They happen to agree in v1.3.0, but
the entire reason the probe exists is that the skill cannot assume what a given
CLI version exposes — so a probe that answers for the wrong verb is a probe that
has quietly stopped doing its job.

This is enforced at the source level rather than behaviourally because the
divergence being guarded against (verb A advertises `--page`, verb B does not)
requires a stub that varies `--help` output per subcommand, which the shared
harness in test_repository.py does not model.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'revenium' / 'scripts'

# script -> {gating variable: the verb whose --help must have been probed}
EXPECTED_PROBE_SCOPE = {
    'guardrail-check.sh': {
        'PAGE_FLAG_SUPPORTED': 'guardrails enforcement-events list',
        'BUDGET_RULES_PAGE_FLAG_SUPPORTED': 'guardrails budget-rules list',
    },
    'setup-guardrails.sh': {
        'PAGE_FLAG_SUPPORTED': 'guardrails budget-rules list',
        'ALERTS_PAGE_FLAG_SUPPORTED': 'alerts budget list',
    },
}

# gating variable -> the revenium verb its guarded command block must invoke
EXPECTED_GATED_VERB = {
    'guardrail-check.sh': {
        'PAGE_FLAG_SUPPORTED': 'revenium guardrails enforcement-events list',
        'BUDGET_RULES_PAGE_FLAG_SUPPORTED': 'revenium guardrails budget-rules list',
    },
    'setup-guardrails.sh': {
        'PAGE_FLAG_SUPPORTED': 'revenium guardrails budget-rules list',
        'ALERTS_PAGE_FLAG_SUPPORTED': 'revenium alerts budget list',
    },
}


class PaginationProbeScopeTests(unittest.TestCase):
    def test_each_gating_variable_is_assigned_from_its_own_verb_probe(self):
        """`VAR=true` must sit inside `if supports_flag "<its own verb>" ...`."""
        for script, expectations in EXPECTED_PROBE_SCOPE.items():
            source = (SCRIPTS / script).read_text()
            for var, verb in expectations.items():
                pattern = (
                    r'if\s+supports_flag\s+"' + re.escape(verb) + r'"\s+"--page"\s*;\s*then\s*\n'
                    r'\s*' + re.escape(var) + r'=true'
                )
                self.assertRegex(
                    source, pattern,
                    f'{script}: {var} must be assigned from a supports_flag probe of '
                    f'"{verb}" — its own gated verb. A probe of a different '
                    f'subcommand does not answer whether "{verb}" accepts --page.',
                )

    def test_no_gating_variable_guards_a_foreign_verb(self):
        """Each `if [[ "${VAR}" == "true" ]]` block must append pagination flags
        to a command invoking that variable's own verb."""
        for script, expectations in EXPECTED_GATED_VERB.items():
            source = (SCRIPTS / script).read_text()
            lines = source.splitlines()
            for idx, line in enumerate(lines):
                m = re.search(r'\[\[\s*"\$\{(\w*PAGE_FLAG_SUPPORTED)\}"\s*==\s*"true"\s*\]\]', line)
                if not m:
                    continue
                var = m.group(1)
                self.assertIn(
                    var, expectations,
                    f'{script}:{idx + 1} gates on unknown variable {var} — add it to '
                    f'this test with the verb it is allowed to guard.',
                )
                expected_verb = expectations[var]
                # The command array is built in the ~6 lines immediately above
                # the gate; that is where the verb appears.
                window = '\n'.join(lines[max(0, idx - 6):idx])
                self.assertIn(
                    expected_verb, window,
                    f'{script}:{idx + 1}: {var} guards a command block that does not '
                    f'invoke "{expected_verb}". Pagination support probed for one '
                    f'subcommand must not gate a different subcommand.',
                )

    def test_every_probed_verb_is_actually_gated(self):
        """No dead probes: each declared variable must have a real gate site,
        so the extra `--help` spawn buys something."""
        for script, expectations in EXPECTED_GATED_VERB.items():
            source = (SCRIPTS / script).read_text()
            for var in expectations:
                self.assertIn(
                    f'[[ "${{{var}}}" == "true" ]]', source,
                    f'{script}: {var} is probed but never gates a call site.',
                )


if __name__ == '__main__':
    unittest.main()
