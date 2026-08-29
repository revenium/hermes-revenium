"""costs-status.sh — the read-only surface reporting which classified job
types carry no configured cost figures.

The behaviour under test is mostly about what this script must NOT do. It
must never write config.json and must never emit a cost number, because
per classifier.py's _resolve_supplied_costs a supplied `0` is knowledge
that participates in the net_value subtraction while an absent category is
unknown and never participates. A script that scaffolded zeros to silence
itself would manufacture operator knowledge nobody supplied.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'revenium' / 'scripts' / 'costs-status.sh'


class CostsStatusTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = Path(self.tmp) / 'state' / 'revenium'
        self.state.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, taxonomy=None, config=None):
        if taxonomy is not None:
            (self.state / 'job-taxonomy.json').write_text(json.dumps(taxonomy))
        if config is not None:
            (self.state / 'config.json').write_text(json.dumps(config))

    def _run(self, *args):
        env = dict(os.environ)
        env['HERMES_HOME'] = self.tmp
        env['REVENIUM_STATE_DIR'] = str(self.state)
        return subprocess.run(
            ['bash', str(SCRIPT), *args],
            capture_output=True, text=True, env=env,
        )

    def _costs(self, mapping):
        return {'llmOutcomeEvaluation': {'costs': mapping}}

    def test_all_priced_exits_zero(self):
        self._write({'labels': {'a': {}}}, self._costs({'a': {'human_review': 25}}))
        self.assertEqual(self._run().returncode, 0)

    def test_unpriced_exits_ten_and_names_the_job_type(self):
        self._write({'labels': {'a': {}, 'b': {}}}, self._costs({'a': {'human_review': 25}}))
        r = self._run()
        self.assertEqual(r.returncode, 10)
        self.assertIn('b', r.stdout)

    def test_empty_cost_object_counts_as_unpriced(self):
        """An empty object resolves every category to unknown, exactly as
        absence does, so it must not read as configured."""
        self._write({'labels': {'a': {}}}, self._costs({'a': {}}))
        self.assertEqual(self._run().returncode, 10)

    def test_boolean_and_negative_are_not_prices(self):
        """Mirrors _resolve_supplied_costs: a malformed value fails closed
        to unknown, never to zero."""
        self._write(
            {'labels': {'a': {}}},
            self._costs({'a': {'human_review': True, 'handoff': -5}}),
        )
        self.assertEqual(self._run().returncode, 10)

    def test_supplied_zero_is_a_price(self):
        """A supplied 0 is knowledge and participates in the subtraction,
        so a job type carrying one is configured, not outstanding."""
        self._write({'labels': {'a': {}}}, self._costs({'a': {'handoff': 0}}))
        self.assertEqual(self._run().returncode, 0)

    def test_missing_config_reports_everything_unpriced(self):
        self._write({'labels': {'a': {}}})
        self.assertEqual(self._run().returncode, 10)

    def test_missing_taxonomy_cannot_determine(self):
        self._write(config=self._costs({'a': {'human_review': 1}}))
        self.assertEqual(self._run().returncode, 1)

    def test_orphan_cost_key_is_surfaced(self):
        self._write({'labels': {'a': {}}}, self._costs({'a': {'human_review': 1}, 'gone': {'handoff': 2}}))
        r = self._run()
        self.assertIn('gone', r.stdout)

    def test_quiet_prints_only_names(self):
        self._write({'labels': {'a': {}, 'b': {}}}, self._costs({'a': {'human_review': 1}}))
        r = self._run('--quiet')
        self.assertEqual(r.stdout.split(), ['b'])

    def test_never_writes_config_or_taxonomy(self):
        """The load-bearing property: this surface is read-only."""
        tax = {'labels': {'a': {}, 'b': {}}}
        cfg = self._costs({'a': {'human_review': 1}})
        self._write(tax, cfg)
        before = {
            p.name: p.read_bytes()
            for p in self.state.iterdir() if p.is_file()
        }
        self._run()
        self._run('--quiet')
        after = {
            p.name: p.read_bytes()
            for p in self.state.iterdir() if p.is_file()
        }
        self.assertEqual(before, after, 'costs-status.sh must not write state')

    def test_emits_no_cost_number_for_an_unpriced_type(self):
        """It must not scaffold a figure -- not even 0 -- for a job type
        the operator has not priced."""
        self._write({'labels': {'unpriced_type': {}}}, self._costs({}))
        out = self._run().stdout
        self.assertIn('unpriced_type', out)
        line = [l for l in out.splitlines() if 'unpriced_type' in l][0]
        self.assertNotIn('0', line)
        self.assertNotIn(':', line)

    def test_unrecognised_category_is_not_a_price(self):
        """_resolve_supplied_costs ignores a key outside COST_CATEGORIES
        "entirely -- absent from supplied_costs, from every coverage list,
        and from the subtraction", so it cannot make a job type priced."""
        self._write({'labels': {'a': {}}}, self._costs({'a': {'bogus_category': 50}}))
        self.assertEqual(self._run().returncode, 10)

    def test_non_finite_values_are_not_prices(self):
        """A non-finite value fails closed to unknown in the resolver."""
        for literal in ('Infinity', '-Infinity', 'NaN'):
            with self.subTest(literal=literal):
                (self.state / 'job-taxonomy.json').write_text('{"labels":{"a":{}}}')
                (self.state / 'config.json').write_text(
                    '{"llmOutcomeEvaluation":{"costs":{"a":{"human_review":%s}}}}' % literal
                )
                self.assertEqual(self._run().returncode, 10)

    def test_unreadable_config_is_could_not_determine_not_unpriced(self):
        """A config that EXISTS but cannot be parsed may contain prices this
        script cannot see. Reporting those job types as unpriced would be a
        false claim -- that is exit 1, not exit 10."""
        (self.state / 'job-taxonomy.json').write_text('{"labels":{"a":{}}}')
        (self.state / 'config.json').write_text('{not valid json')
        r = self._run()
        self.assertEqual(r.returncode, 1)
        self.assertIn('could not be read', r.stderr)

    def test_non_object_config_is_could_not_determine(self):
        (self.state / 'job-taxonomy.json').write_text('{"labels":{"a":{}}}')
        (self.state / 'config.json').write_text('[]')
        self.assertEqual(self._run().returncode, 1)

    def test_absent_config_is_unpriced_not_an_error(self):
        """Absent is different from unreadable: nothing is priced, and that
        is a legitimate reportable state."""
        self._write({'labels': {'a': {}}})
        self.assertEqual(self._run().returncode, 10)

    def test_cost_categories_match_the_classifier(self):
        """Third declaration of the four names; drift makes the report
        disagree with the resolver about what counts as priced."""
        import re
        script = (ROOT / 'skills' / 'revenium' / 'scripts' / 'costs-status.sh').read_text()
        classifier = (
            ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier' / 'classifier.py'
        ).read_text()
        mine = re.search(r"^COST_CATEGORIES = \(([^)]*)\)", script, re.M).group(1)
        theirs = re.search(r"^COST_CATEGORIES = \(([^)]*)\)", classifier, re.M).group(1)
        norm = lambda t: [x.strip().strip('\'"') for x in t.split(',') if x.strip()]
        self.assertEqual(norm(mine), norm(theirs))


if __name__ == '__main__':
    unittest.main()
