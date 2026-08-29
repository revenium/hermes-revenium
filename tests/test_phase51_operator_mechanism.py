"""Phase 51 — operator-declared economic mechanism (MECH-01/02/04, D-08).

correct-assessment.sh may now declare any of the six mechanisms, including
the three the evaluator structurally cannot reach, and --value is required
only when --mechanism is absent.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'revenium' / 'scripts' / 'correct-assessment.sh'
CLASSIFIER = ROOT / 'skills' / 'revenium' / 'plugins' / 'revenium-classifier' / 'classifier.py'

OPERATOR_ONLY = ('quality_decision_improvement', 'risk_avoidance', 'incremental_revenue')
EVALUATOR_THREE = ('labor_substitution', 'augmentation_capacity_expansion', 'newly_enabled_work')

_STUB = """#!/usr/bin/env bash
if [[ "$*" == *"--help"* ]]; then echo "--reason string"; exit 0; fi
if [[ "$1" == "config" ]]; then echo "Team ID:    TEAMX"; exit 0; fi
printf '%s\\n' "$*" >> "${REVENIUM_ARGV_LOG}"
exit 0
"""


class OperatorMechanismTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = Path(self.tmp) / 'state' / 'revenium'
        (self.state / 'job-assessments').mkdir(parents=True)
        self.bin = Path(self.tmp) / 'bin'
        self.bin.mkdir()
        stub = self.bin / 'revenium'
        stub.write_text(_STUB)
        stub.chmod(0o755)
        self.argv_log = Path(self.tmp) / 'argv.log'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed(self, job_id, **over):
        rec = {
            'kind': 'job_assessment', 'ts': time.time(), 'agentic_job_id': job_id,
            'assessment_id': 'c:0', 'sequence': 0, 'assessment_schema_version': 1,
            'value_low': 10.0, 'value_base': 20.0, 'value_high': 30.0, 'currency': 'USD',
        }
        rec.update(over)
        path = self.state / 'job-assessments' / f'{job_id}.jsonl'
        path.write_text(json.dumps(rec) + '\n')
        return path

    def _run(self, *args):
        env = dict(os.environ)
        env['PATH'] = f'{self.bin}{os.pathsep}' + env['PATH']
        env['HERMES_HOME'] = self.tmp
        env['REVENIUM_STATE_DIR'] = str(self.state)
        env['REVENIUM_ARGV_LOG'] = str(self.argv_log)
        return subprocess.run(['bash', str(SCRIPT), *args],
                              capture_output=True, text=True, env=env)

    def _corrections(self, path):
        return [json.loads(l) for l in path.read_text().splitlines()
                if json.loads(l).get('kind') == 'correction']

    # ---- MECH-01: the allow-list -------------------------------------

    def test_all_six_mechanisms_are_accepted(self):
        for m in OPERATOR_ONLY + EVALUATOR_THREE:
            with self.subTest(mechanism=m):
                p = self._seed(f'job-{m}')
                r = self._run('--job-id', f'job-{m}', '--mechanism', m, '--reason', 'x')
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self._corrections(p)[-1]['economic_mechanism'], m)

    def test_out_of_set_mechanism_is_refused_not_coerced(self):
        """D-03's discipline: an out-of-set value is refused. This path
        diverges from _resolve_economic_mechanism only in failing LOUDLY
        rather than abstaining (D-04) -- it never coerces."""
        for bad in ('Labor_Substitution', 'LABOR_SUBSTITUTION', 'bogus', 'labor substitution'):
            with self.subTest(value=bad):
                self._seed('job-bad')
                r = self._run('--job-id', 'job-bad', '--mechanism', bad, '--reason', 'x')
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('Unsupported --mechanism', r.stderr)

    def test_explicitly_empty_mechanism_is_refused(self):
        """`--mechanism ""` is an explicit request carrying an out-of-set
        value; treating it as 'no mechanism' would be the coercion the
        allow-list exists to refuse."""
        for bad in ('', '   '):
            with self.subTest(value=repr(bad)):
                self._seed('job-empty')
                r = self._run('--job-id', 'job-empty', '--mechanism', bad, '--reason', 'x')
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('Unsupported --mechanism', r.stderr)

    def test_surrounding_whitespace_is_stripped_not_rejected(self):
        """_resolve_economic_mechanism applies .strip(); mirrored here."""
        p = self._seed('job-ws')
        r = self._run('--job-id', 'job-ws', '--mechanism', '  risk_avoidance  ', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._corrections(p)[-1]['economic_mechanism'], 'risk_avoidance')

    def test_mechanism_vocabulary_matches_the_classifier(self):
        """Third declaration of the six names; drift would let this script
        accept a mechanism the resolver does not know."""
        import re
        script = SCRIPT.read_text()
        mine = set(re.search(r'^_MECHANISMS="([^"]+)"', script, re.M).group(1).split())
        block = re.search(r'^ECONOMIC_MECHANISMS = frozenset\(\{(.*?)\}\)',
                          CLASSIFIER.read_text(), re.M | re.S).group(1)
        theirs = set(re.findall(r'"([a-z_]+)"', block))
        self.assertEqual(mine, theirs)

    # ---- D-08: --value conditional -----------------------------------

    def test_mechanism_only_correction_needs_no_value(self):
        p = self._seed('job-mo')
        r = self._run('--job-id', 'job-mo', '--mechanism', 'incremental_revenue', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_value_family_is_absent_not_null_on_a_mechanism_only_correction(self):
        """Absent, not null and not zero -- the same distinction the value
        docs draw for an abstained record."""
        p = self._seed('job-abs')
        self._run('--job-id', 'job-abs', '--mechanism', 'risk_avoidance', '--reason', 'x')
        c = self._corrections(p)[-1]
        for key in ('value_low', 'value_base', 'value_high', 'currency'):
            self.assertNotIn(key, c)
        self.assertEqual(c['prior_value_base'], 20.0)

    def test_neither_value_nor_mechanism_is_refused(self):
        self._seed('job-none')
        r = self._run('--job-id', 'job-none', '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)

    def test_value_without_currency_is_refused(self):
        self._seed('job-nc')
        r = self._run('--job-id', 'job-nc', '--value', '5', '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)

    def test_bounds_without_value_are_refused(self):
        self._seed('job-nb')
        r = self._run('--job-id', 'job-nb', '--mechanism', 'risk_avoidance',
                      '--value-low', '5', '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)

    def test_value_only_correction_is_unchanged(self):
        """The pre-existing path must behave exactly as before."""
        p = self._seed('job-vo')
        r = self._run('--job-id', 'job-vo', '--value', '42', '--currency', 'USD', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self._corrections(p)[-1]
        self.assertEqual((c['value_low'], c['value_base'], c['value_high']), (42.0, 42.0, 42.0))
        self.assertEqual(c['currency'], 'USD')
        self.assertNotIn('economic_mechanism', c)

    # ---- MECH-02 / MECH-04: append-only, and the wire ----------------

    def test_correction_appends_and_preserves_the_original(self):
        p = self._seed('job-app')
        self._run('--job-id', 'job-app', '--mechanism', 'risk_avoidance', '--reason', 'x')
        lines = [json.loads(l) for l in p.read_text().splitlines()]
        self.assertEqual(lines[0]['kind'], 'job_assessment')
        self.assertEqual(lines[0]['value_base'], 20.0)
        self.assertEqual(lines[-1]['kind'], 'correction')

    def test_operator_only_mechanisms_reach_the_wire(self):
        """MECH-04 says end to end, so assert on the shipped argv."""
        for m in OPERATOR_ONLY:
            with self.subTest(mechanism=m):
                self._seed(f'job-w-{m}')
                r = self._run('--job-id', f'job-w-{m}', '--mechanism', m, '--reason', 'x')
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f'"economic_mechanism":"{m}"', self.argv_log.read_text())

    def test_mechanism_only_ships_no_empty_outcome_value(self):
        """--outcome-value is a float64 flag; passing "" would be a
        malformed invocation rather than an omission."""
        self._seed('job-nov')
        self._run('--job-id', 'job-nov', '--mechanism', 'risk_avoidance', '--reason', 'x')
        self.assertNotIn('--outcome-value', self.argv_log.read_text())

    def test_dry_run_writes_nothing_on_the_mechanism_path(self):
        p = self._seed('job-dr')
        before = p.read_bytes()
        r = self._run('--job-id', 'job-dr', '--mechanism', 'incremental_revenue',
                      '--reason', 'x', '--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse(self.argv_log.exists() and self.argv_log.read_text().strip())


if __name__ == '__main__':
    unittest.main()
