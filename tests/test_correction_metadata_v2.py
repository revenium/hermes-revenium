"""The operator correction path speaks the schema_version 2 --metadata vocabulary.

`revenium jobs outcome` already ships the nested v2 envelope (built by the
`outcome_metadata` heredoc in hermes-report.sh). `correct-assessment.sh` Step 8
used to send v1 flat keys (assessment_schema_version, sequence, prior_value_*,
prior_currency, economic_mechanism, attribution_fraction, attribution_basis)
to `jobs outcome-update --metadata`. These tests pin the v2 shape so both verbs
speak one schema:

    {"schema_version":2,"corrected":true,"correction_sequence":N,
     "value":{"reported":R,"currency":C,"attribution":{"fraction":F,"basis":B}},
     "basis":{"mechanism":M},
     "prior":{"low":..,"base":..,"high":..,"currency":..}}

Only the wire metadata moved. The local sidecar correction record keeps its v1
names; that is asserted here too, because a rename there would orphan every
correction already on disk.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import meta_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills' / 'revenium' / 'scripts' / 'correct-assessment.sh'

_STUB = """#!/usr/bin/env bash
if [[ "$*" == *"--help"* ]]; then echo "--reason string"; echo "--metadata string"; exit 0; fi
if [[ "$1" == "config" ]]; then echo "Team ID:    TEAMX"; exit 0; fi
{ printf '%s\\037' "$@"; printf '\\n'; } >> "${REVENIUM_ARGV_LOG}"
exit 0
"""

_V1_KEYS = (
    'assessment_schema_version', 'sequence', 'prior_value_low', 'prior_value_base',
    'prior_value_high', 'prior_currency', 'economic_mechanism',
    'attribution_fraction', 'attribution_basis',
)


class CorrectionMetadataV2Tests(unittest.TestCase):

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

    def _argv(self):
        """The last `jobs outcome-update` argv the stub saw, as a token list."""
        lines = [l for l in self.argv_log.read_text().split('\n') if l]
        argv = lines[-1].rstrip('\x1f').split('\x1f')
        self.assertEqual(argv[:2], ['jobs', 'outcome-update'], argv)
        return argv

    def _metadata(self):
        argv = self._argv()
        raw = argv[argv.index('--metadata') + 1]
        return raw, json.loads(raw)

    # ---- exact shape --------------------------------------------------

    def test_golden_correction_has_the_exact_v2_shape(self):
        self._seed('job-gold')
        r = self._run('--job-id', 'job-gold', '--value', '102', '--currency', 'usd',
                      '--mechanism', 'incremental_revenue',
                      '--attribution-fraction', '0.15',
                      '--attribution-basis', '15% per policy REV-2024-03',
                      '--reason', 'confirmed booking')
        self.assertEqual(r.returncode, 0, r.stderr)
        raw, _ = self._metadata()
        self.assertEqual(
            raw,
            '{"schema_version":2,"corrected":true,"correction_sequence":1,'
            '"value":{"reported":102.0,"currency":"USD",'
            '"attribution":{"fraction":0.15,"basis":"15% per policy REV-2024-03"}},'
            '"basis":{"mechanism":"incremental_revenue"},'
            '"prior":{"low":10.0,"base":20.0,"high":30.0,"currency":"USD"}}',
        )

    def test_no_v1_flat_key_survives_on_the_wire(self):
        self._seed('job-v1')
        r = self._run('--job-id', 'job-v1', '--value', '5', '--currency', 'USD',
                      '--mechanism', 'risk_avoidance',
                      '--attribution-fraction', '1', '--attribution-basis', 'b',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        for key in _V1_KEYS:
            self.assertNotIn(key, meta)
        self.assertEqual(list(meta), ['schema_version', 'corrected',
                                      'correction_sequence', 'value', 'basis', 'prior'])
        self.assertIs(meta_path(meta, 'corrected'), True)

    def test_correction_sequence_counts_prior_corrections(self):
        self._seed('job-seq')
        for _ in range(2):
            r = self._run('--job-id', 'job-seq', '--value', '5', '--currency', 'USD',
                          '--reason', 'x')
            self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        self.assertEqual(meta_path(meta, 'correction_sequence'), 2)
        # The second correction's prior is the first correction's value.
        self.assertEqual(meta_path(meta, 'prior.base'), 5.0)

    # ---- value.reported equals the argv token -------------------------

    def test_value_reported_equals_the_outcome_value_argv_token(self):
        for token in ('102', '0.5', '1250.75', '1e3'):
            with self.subTest(value=token):
                self._seed('job-rep')
                r = self._run('--job-id', 'job-rep', '--value', token,
                              '--currency', 'EUR', '--reason', 'x')
                self.assertEqual(r.returncode, 0, r.stderr)
                argv = self._argv()
                sent = argv[argv.index('--outcome-value') + 1]
                _, meta = self._metadata()
                self.assertEqual(meta_path(meta, 'value.reported'), float(sent))
                self.assertEqual(
                    meta_path(meta, 'value.currency'),
                    argv[argv.index('--outcome-currency') + 1],
                )

    def test_range_flags_do_not_move_value_reported(self):
        """value.reported is the --outcome-value this call sends, not a bound."""
        self._seed('job-rng')
        r = self._run('--job-id', 'job-rng', '--value', '100', '--value-low', '80',
                      '--value-high', '120', '--currency', 'USD', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self._argv()
        sent = float(argv[argv.index('--outcome-value') + 1])
        _, meta = self._metadata()
        self.assertEqual(meta_path(meta, 'value.reported'), sent)

    # ---- attribution pair rules ----------------------------------------

    def test_attribution_pair_travels_together(self):
        self._seed('job-pair')
        r = self._run('--job-id', 'job-pair', '--value', '5', '--currency', 'USD',
                      '--attribution-fraction', '0.4', '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('requires --attribution-basis', r.stderr)
        self.assertFalse(self.argv_log.exists() and self.argv_log.read_text().strip())

        r = self._run('--job-id', 'job-pair', '--value', '5', '--currency', 'USD',
                      '--attribution-basis', 'orphan basis', '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.argv_log.exists() and self.argv_log.read_text().strip())

    def test_attribution_requires_a_value_so_a_mechanism_only_blob_has_none(self):
        self._seed('job-mo-attr')
        r = self._run('--job-id', 'job-mo-attr', '--mechanism', 'risk_avoidance',
                      '--attribution-fraction', '0.4', '--attribution-basis', 'b',
                      '--reason', 'x')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('requires --value', r.stderr)

    def test_attribution_fraction_is_a_number_and_basis_is_sanitised(self):
        self._seed('job-san')
        r = self._run('--job-id', 'job-san', '--value', '5', '--currency', 'USD',
                      '--attribution-fraction', '0.25',
                      '--attribution-basis', '  a|b\nc\rd  ', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        self.assertEqual(meta_path(meta, 'value.attribution.fraction'), 0.25)
        self.assertEqual(meta_path(meta, 'value.attribution.basis'), 'a b c d')

    def test_attribution_basis_is_capped_at_500_serialised_bytes(self):
        self._seed('job-cap')
        r = self._run('--job-id', 'job-cap', '--value', '5', '--currency', 'USD',
                      '--attribution-fraction', '0.5',
                      '--attribution-basis', 'b' * 900, '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        raw, meta = self._metadata()
        basis = meta_path(meta, 'value.attribution.basis')
        self.assertTrue(basis)
        self.assertLessEqual(len(json.dumps(basis, ensure_ascii=True).encode('utf-8')), 500)
        self.assertEqual(basis, 'b' * len(basis))
        self.assertGreater(len(basis), 400)
        self.assertNotIn('\n', raw)

    def test_attribution_absent_when_no_pair_is_given(self):
        self._seed('job-noattr')
        r = self._run('--job-id', 'job-noattr', '--value', '5', '--currency', 'USD',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        self.assertNotIn('attribution', meta['value'])

    # ---- omission of absent members ------------------------------------

    def test_mechanism_only_correction_has_no_value_group(self):
        self._seed('job-mo')
        r = self._run('--job-id', 'job-mo', '--mechanism', 'risk_avoidance', '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('--outcome-value', self._argv())
        raw, meta = self._metadata()
        self.assertNotIn('value', meta)
        self.assertEqual(
            raw,
            '{"schema_version":2,"corrected":true,"correction_sequence":1,'
            '"basis":{"mechanism":"risk_avoidance"},'
            '"prior":{"low":10.0,"base":20.0,"high":30.0,"currency":"USD"}}',
        )

    def test_no_mechanism_means_no_basis_group(self):
        self._seed('job-nomech')
        r = self._run('--job-id', 'job-nomech', '--value', '7', '--currency', 'USD',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        self.assertNotIn('basis', meta)

    def test_absent_priors_are_omitted_not_nulled(self):
        """A record that held no valuation has nothing to supersede: the whole
        `prior` group is absent, not {} and not nulls."""
        self._seed('job-noprior', value_low=None, value_base=None, value_high=None,
                   currency=None)
        r = self._run('--job-id', 'job-noprior', '--value', '9', '--currency', 'USD',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        raw, meta = self._metadata()
        self.assertNotIn('prior', meta)
        self.assertNotIn('null', raw)
        self.assertNotIn('{}', raw)
        self.assertEqual(
            raw,
            '{"schema_version":2,"corrected":true,"correction_sequence":1,'
            '"value":{"reported":9.0,"currency":"USD"}}',
        )

    def test_partial_priors_keep_only_what_exists(self):
        self._seed('job-partial', value_low=None, value_high=None, value_base=20.0)
        r = self._run('--job-id', 'job-partial', '--value', '9', '--currency', 'USD',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, meta = self._metadata()
        self.assertEqual(meta['prior'], {'base': 20.0, 'currency': 'USD'})

    # ---- compact, deterministic ----------------------------------------

    def test_blob_is_compact_and_deterministic(self):
        self._seed('job-det')
        args = ('--job-id', 'job-det', '--value', '5', '--currency', 'USD',
                '--mechanism', 'risk_avoidance', '--reason', 'x')
        self.assertEqual(self._run(*args).returncode, 0)
        first, _ = self._metadata()
        self._seed('job-det')
        self.assertEqual(self._run(*args).returncode, 0)
        second, _ = self._metadata()
        self.assertEqual(first, second)
        self.assertNotIn(', ', first)
        self.assertNotIn(': ', first)

    # ---- the local sidecar record did not move --------------------------

    def test_sidecar_correction_keeps_its_v1_names(self):
        path = self._seed('job-side')
        r = self._run('--job-id', 'job-side', '--value', '102', '--currency', 'USD',
                      '--mechanism', 'incremental_revenue',
                      '--attribution-fraction', '0.15', '--attribution-basis', 'policy',
                      '--reason', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = [json.loads(l) for l in path.read_text().splitlines()][-1]
        self.assertEqual(rec['kind'], 'correction')
        for key in ('assessment_schema_version', 'sequence', 'prior_value_low',
                    'prior_value_base', 'prior_value_high', 'prior_currency',
                    'economic_mechanism', 'attribution_fraction', 'attribution_basis',
                    'value_base', 'currency'):
            self.assertIn(key, rec)
        self.assertNotIn('schema_version', rec)


if __name__ == '__main__':
    unittest.main()
