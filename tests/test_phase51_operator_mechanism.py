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

    # ---- D-01/D-05: attribution ---------------------------------------

    def test_attribution_pair_is_recorded_and_shipped(self):
        p = self._seed('job-attr')
        r = self._run('--job-id', 'job-attr', '--value', '102', '--currency', 'USD',
                      '--mechanism', 'incremental_revenue',
                      '--attribution-fraction', '0.15',
                      '--attribution-basis', '15% per policy REV-2024-03',
                      '--reason', 'confirmed booking')
        self.assertEqual(r.returncode, 0, r.stderr)
        c = self._corrections(p)[-1]
        self.assertEqual(c['attribution_fraction'], 0.15)
        self.assertEqual(c['attribution_basis'], '15% per policy REV-2024-03')
        self.assertEqual(c['value_base'], 102.0)
        wire = self.argv_log.read_text()
        self.assertIn('"attribution_fraction":0.15', wire)
        self.assertIn('attribution_basis', wire)

    def test_no_gross_figure_is_derived_or_stored(self):
        """D-05: the operator supplies the already-attributed value. The
        skill multiplies nothing, so 102 stays 102 -- it is never treated
        as a gross to be reduced, and no gross ever enters the record."""
        p = self._seed('job-gross')
        self._run('--job-id', 'job-gross', '--value', '102', '--currency', 'USD',
                  '--attribution-fraction', '0.15', '--attribution-basis', 'b',
                  '--reason', 'x')
        c = self._corrections(p)[-1]
        self.assertEqual(c['value_base'], 102.0)
        for v in c.values():
            self.assertNotEqual(v, 680.0)
            self.assertNotEqual(v, 15.3)

    def test_fraction_requires_basis(self):
        """The one constraint available: a fraction cannot be validated
        against anything here, so it may never travel naked."""
        self._seed('job-nb2')
        for basis in (None, '', '   '):
            with self.subTest(basis=repr(basis)):
                args = ['--job-id', 'job-nb2', '--value', '5', '--currency', 'USD',
                        '--reason', 'x', '--attribution-fraction', '0.5']
                if basis is not None:
                    args += ['--attribution-basis', basis]
                r = self._run(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('requires --attribution-basis', r.stderr)

    def test_basis_requires_fraction(self):
        self._seed('job-bo')
        r = self._run('--job-id', 'job-bo', '--value', '5', '--currency', 'USD',
                      '--reason', 'x', '--attribution-basis', 'lonely')
        self.assertNotEqual(r.returncode, 0)

    def test_fraction_rejection_set(self):
        for bad in ('1.5', '-0.1', 'abc', 'NaN', 'Infinity', '-Infinity', '9' * 400):
            with self.subTest(value=bad):
                self._seed('job-fr')
                r = self._run('--job-id', 'job-fr', '--value', '5', '--currency', 'USD',
                              '--reason', 'x', '--attribution-fraction', bad,
                              '--attribution-basis', 'b')
                self.assertNotEqual(r.returncode, 0, f'{bad!r} was accepted')

    def test_zero_and_one_are_legal_fractions(self):
        for f in ('0', '1', '0.0', '1.0'):
            with self.subTest(fraction=f):
                p = self._seed('job-edge')
                r = self._run('--job-id', 'job-edge', '--value', '5', '--currency', 'USD',
                              '--reason', 'x', '--attribution-fraction', f,
                              '--attribution-basis', 'edge case')
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self._corrections(p)[-1]['attribution_fraction'], float(f))

    def test_basis_is_clamped_like_reason(self):
        p = self._seed('job-clamp')
        long_basis = 'A' * 900 + '|pipe\nnewline'
        r = self._run('--job-id', 'job-clamp', '--value', '5', '--currency', 'USD',
                      '--reason', 'x', '--attribution-fraction', '0.5',
                      '--attribution-basis', long_basis)
        self.assertEqual(r.returncode, 0, r.stderr)
        basis = self._corrections(p)[-1]['attribution_basis']
        self.assertLessEqual(len(json.dumps(basis, ensure_ascii=True).encode()), 500)
        for bad in ('|', '\n', '\r'):
            self.assertNotIn(bad, basis)

    # ---- MECH-03 / D-06: the label may not move -----------------------

    def test_mechanism_never_moves_evidence_class(self):
        """MECH-03: mechanism and evidence label are orthogonal (EGV-10)."""
        for m in OPERATOR_ONLY + EVALUATOR_THREE:
            with self.subTest(mechanism=m):
                p = self._seed('job-ec', evidence_class='MODEL_ESTIMATED_DEMO')
                self._run('--job-id', 'job-ec', '--mechanism', m, '--reason', 'x')
                c = self._corrections(p)[-1]
                self.assertNotIn('evidence_class', c)
                first = json.loads(p.read_text().splitlines()[0])
                self.assertEqual(first['evidence_class'], 'MODEL_ESTIMATED_DEMO')

    def test_attribution_never_moves_evidence_class(self):
        """D-06: a declared fraction is an operator assertion, not evidence.
        Not even a fraction of 1 promotes the label."""
        for f in ('0', '0.5', '1'):
            with self.subTest(fraction=f):
                p = self._seed('job-ec2', evidence_class='MODEL_ESTIMATED_DEMO')
                self._run('--job-id', 'job-ec2', '--value', '5', '--currency', 'USD',
                          '--reason', 'x', '--attribution-fraction', f,
                          '--attribution-basis', 'b')
                c = self._corrections(p)[-1]
                self.assertNotIn('evidence_class', c)

    def test_no_correction_reaches_a_reserved_causal_label(self):
        """The three labels Phase 43 shut off and Phase 48's Falsifier 3
        guards must be unreachable from any operator flag."""
        reserved = ('ASSOCIATIONAL', 'QUASI_EXPERIMENTAL_IMPACT', 'EXPERIMENTAL_IMPACT')
        p = self._seed('job-res', evidence_class='MODEL_ESTIMATED_DEMO')
        self._run('--job-id', 'job-res', '--value', '5', '--currency', 'USD',
                  '--mechanism', 'incremental_revenue', '--reason', 'x',
                  '--attribution-fraction', '1', '--attribution-basis', 'b')
        blob = p.read_text() + self.argv_log.read_text()
        for label in reserved:
            self.assertNotIn(label, blob)

    def test_attribution_does_not_set_customer_configured(self):
        """Letting an operator flag move the label is the coupling Phases
        43-48 exist to prevent -- including toward CUSTOMER_CONFIGURED."""
        p = self._seed('job-cc', evidence_class='MODEL_ESTIMATED_DEMO')
        self._run('--job-id', 'job-cc', '--value', '5', '--currency', 'USD',
                  '--reason', 'x', '--attribution-fraction', '0.5',
                  '--attribution-basis', 'b')
        self.assertNotIn('CUSTOMER_CONFIGURED', p.read_text())


class ReporterAttributionAndValueTests(unittest.TestCase):
    """Greptile findings on PR #110, both against hermes-report.sh's reader
    rather than the operator CLI -- the reporter reads whatever is on disk,
    so the CLI's own guarantees do not bind it."""

    def _forwarder_src(self):
        return (ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh').read_text()

    def test_attribution_pair_is_gated_together_not_separately(self):
        """A legacy or hand-edited sidecar can carry a valid fraction with no
        basis. Shipping the fraction alone would put a naked number on the
        wire, defeating the single constraint the design rests on."""
        src = self._forwarder_src()
        i = src.index("attribution_fraction = record.get('attribution_fraction')")
        block = src[i:i + 1400]
        frac_at = block.index("meta['attribution_fraction']")
        basis_guard = block.index("attribution_basis.strip()")
        self.assertLess(
            basis_guard, frac_at,
            'the basis must be validated BEFORE the fraction is inserted, '
            'or a fraction can ship without one',
        )

    def test_correction_promotes_prior_values_into_a_gap(self):
        """A mechanism-only correction carries no value family, and the
        reader replaces the effective record wholesale -- so without
        promotion the reporter drops a standing valuation."""
        src = self._forwarder_src()
        self.assertIn("found.get('kind') == 'correction'", src)
        self.assertIn("('value_base', 'prior_value_base')", src)
        self.assertIn("('currency', 'prior_currency')", src)

    def test_promotion_only_fills_a_gap_never_overrides(self):
        src = self._forwarder_src()
        i = src.index("if found.get(_cur) is None and found.get(_prior) is not None:")
        self.assertGreater(i, 0, 'promotion must be gated on the current value being absent')

    def test_promotion_is_scoped_to_corrections(self):
        """A job_assessment has no prior_value_* and must never be touched."""
        src = self._forwarder_src()
        block_at = src.index("if isinstance(found, dict) and found.get('kind') == 'correction':")
        loop_at = src.index("for _cur, _prior in (", block_at)
        self.assertLess(block_at, loop_at)


if __name__ == '__main__':
    unittest.main()