"""quick-261029-tyq: declare-baseline.sh.

The script writes two things the "Edit Job Type" dialog exposes: a pre-AI
baseline version (PERMANENT: the API appends, never amends or deletes) and the
declared overhead per unit on the economics contract (a whole-document
replace). The properties pinned here are the ones whose failure is silent:

  * nothing is requested before every value is validated locally;
  * a repeated baseline is refused by the local ledger AND by the server's
    version in force, and the ledger line is written only after success;
  * the overhead write sends back every other contract field verbatim, keeps
    an operator's monetization rule and never adds one;
  * a CLI without the verbs is detected from help TEXT (cobra prints the
    parent's help and exits 0 for an unknown subcommand);
  * suggestions are printed, never applied, and the script is never in cron.

Every test drives the REAL script against a stub `revenium` under the test's
own HOME/.local/bin, so ensure_path cannot let the real binary shadow it.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPT = SKILL / 'scripts' / 'declare-baseline.sh'

STUB = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "${STUB_LOG}"
if [ "$1 $2 $3 $4" = "jobs types baselines append" ] && [ "$6" = "--help" -o "$5" = "--help" ]; then
  if [ "${STUB_OLD_CLI:-}" = "1" ]; then
    echo "List available job types"; echo "  revenium jobs types facts append acme --file facts.json"; exit 0
  fi
  echo "Append a new immutable pre-AI baseline version"; echo "      --minutes-per-unit float64"; exit 0
fi
if [ "$1 $2 $3" = "jobs types economics" ] && [ "$4" = "--help" ]; then
  if [ "${STUB_OLD_CLI:-}" = "1" ]; then
    echo "List available job types"; echo "  revenium jobs types economics get acme-review"; exit 0
  fi
  echo "  set   Create or replace a job type's declared economics contract"; exit 0
fi
if [ "$1 $2 $3 $4" = "jobs types economics get" ]; then
  if [ -z "${STUB_ECON:-}" ]; then
    echo '{"error":"Resource not found.","exit_code":3,"status":404}'; exit 3
  fi
  cat "${STUB_ECON}"; exit 0
fi
if [ "$1 $2 $3 $4" = "jobs types economics set" ]; then
  prev=""
  for a in "$@"; do
    if [ "${prev}" = "--file" ]; then cp "${a}" "${STUB_SET_CAPTURE}"; fi
    prev="${a}"
  done
  if [ -t 0 ]; then echo "stdin is a terminal" >&2; exit 9; fi
  echo '{"ok":true}'; exit 0
fi
if [ "$1 $2 $3 $4" = "jobs types baselines list" ]; then
  if [ -n "${STUB_LIST:-}" ]; then printf '%s\n' "${STUB_LIST}"; else echo '[]'; fi
  exit 0
fi
if [ "$1 $2 $3 $4" = "jobs types baselines append" ]; then
  if [ "${STUB_APPEND_FAIL:-}" = "1" ]; then
    echo '{"error":"boom","exit_code":1,"status":500}'; exit 1
  fi
  echo '{"ok":true}'; exit 0
fi
echo "unexpected: $*" >&2; exit 64
'''

CONTRACT = {
    'jobType': 't1',
    'currentBaseline': None,
    'dimensions': [{'key': 'region', 'allowedValues': ['eu', 'us']}],
    'metrics': [
        {'key': 'estimated_value', 'type': 'MONEY', 'direction': 'HIGHER_IS_BETTER',
         'aggregation': 'SUM', 'resolution': 'PER_JOB'},
        {'key': 'jobs_completed', 'type': 'COUNT', 'direction': 'HIGHER_IS_BETTER',
         'aggregation': 'SUM', 'resolution': 'PER_JOB'},
    ],
    'monetization': None,
    'overheadCurrency': None,
    'overheadPerUnit': None,
    'unitLabel': 'Jobs completed',
    'unitMetricKey': 'jobs_completed',
}

BASELINE = ['--minutes-per-unit', '18', '--hourly-rate', '60', '--currency', 'USD',
            '--provenance', 'MEASURED', '--effective-from', '2026-01-07T00:00:00Z']


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self._tmp.name
        hermes_home = os.path.join(tmp, 'hh')
        self.state_dir = os.path.join(hermes_home, 'state', 'revenium')
        os.makedirs(os.path.join(self.state_dir, 'job-assessments'), exist_ok=True)
        home = os.path.join(tmp, 'home')
        bin_dir = os.path.join(home, '.local', 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        stub = os.path.join(bin_dir, 'revenium')
        with open(stub, 'w') as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        self.log = os.path.join(tmp, 'calls.log')
        self.capture = os.path.join(tmp, 'set-doc.json')
        self.ledger = os.path.join(self.state_dir, 'revenium-baselines.ledger')
        self.env = {
            **os.environ,
            'HOME': home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'STUB_LOG': self.log,
            'STUB_SET_CAPTURE': self.capture,
            'TZ': 'UTC',
        }
        for k in ('STUB_ECON', 'STUB_LIST', 'STUB_APPEND_FAIL', 'STUB_OLD_CLI'):
            self.env.pop(k, None)

    def tearDown(self):
        self._tmp.cleanup()

    def contract(self, **over):
        doc = dict(CONTRACT, **over)
        p = os.path.join(self._tmp.name, 'econ.json')
        with open(p, 'w') as f:
            json.dump(doc, f)
        self.env['STUB_ECON'] = p

    def run_script(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)

    def calls(self):
        try:
            return Path(self.log).read_text().splitlines()
        except FileNotFoundError:
            return []

    def writes(self):
        return [c for c in self.calls()
                if c.startswith(('jobs types baselines append t1', 'jobs types economics set'))
                and '--help' not in c]

    def ledger_lines(self):
        try:
            return Path(self.ledger).read_text().splitlines()
        except FileNotFoundError:
            return []

    def assessment(self, job, hours, rate, job_type='t1', currency='USD', seq=0):
        rec = {'kind': 'job_assessment', 'agentic_job_id': job, 'job_type': job_type,
               'sequence': seq, 'ts': 1789742045.0 + seq, 'currency': currency,
               'assumptions': {'estimated_hours_saved': hours, 'assumed_loaded_rate': rate}}
        p = os.path.join(self.state_dir, 'job-assessments', f'{job}.jsonl')
        with open(p, 'a') as f:
            f.write(json.dumps(rec) + '\n')


class ReportModeTests(_Base):
    def test_report_writes_nothing_and_suggests_medians(self):
        self.contract()
        self.assessment('j1', 1.0, 50.0)
        self.assessment('j2', 3.0, 70.0)
        self.assessment('j3', 2.0, 60.0)
        # A later sequence for j3 supersedes its first record.
        self.assessment('j3', 4.0, 80.0, seq=1)
        self.assessment('other', 99.0, 999.0, job_type='t2')
        r = self.run_script('t1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--minutes-per-unit 180.0', r.stdout)
        self.assertIn('--hourly-rate 70.00 --currency USD', r.stdout)
        self.assertIn('MODEL ESTIMATES, never applied', r.stdout)
        self.assertIn('declared overhead per unit: none', r.stdout)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.ledger_lines(), [])

    def test_report_flags_an_existing_monetization_rule(self):
        self.contract(monetization={'ratePerUnit': 1.0, 'currency': 'USD'})
        r = self.run_script('t1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('monetization', r.stdout)


class ValidationTests(_Base):
    def _refused(self, *args):
        r = self.run_script('t1', *args)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.ledger_lines(), [])
        return r.stderr

    def test_quality_rate_above_one_is_refused(self):
        self.assertIn('--quality-rate', self._refused(
            '--quality-rate', '9.5', '--provenance', 'MEASURED'))

    def test_provenance_is_required_and_closed(self):
        self.assertIn('--provenance is required', self._refused('--minutes-per-unit', '5'))
        self.assertIn('--provenance must be one of', self._refused(
            '--minutes-per-unit', '5', '--provenance', 'MODEL_ESTIMATED'))

    def test_money_needs_a_currency(self):
        self.assertIn('--currency is required', self._refused(
            '--cost-per-unit', '3', '--provenance', 'MEASURED'))

    def test_bad_numbers_dates_urls_and_types(self):
        for args in (['--minutes-per-unit', 'nan', '--provenance', 'MEASURED'],
                     ['--minutes-per-unit', '-1', '--provenance', 'MEASURED'],
                     ['--minutes-per-unit', '5', '--provenance', 'MEASURED',
                      '--effective-from', '2026-01-07'],
                     ['--minutes-per-unit', '5', '--provenance', 'MEASURED',
                      '--evidence-url', 'file:///etc/passwd'],
                     ['--overhead-per-unit', 'x']):
            with self.subTest(args=args):
                self._refused(*args)
        r = self.run_script('../t1', '--minutes-per-unit', '5', '--provenance', 'MEASURED')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])


class BaselineAppendTests(_Base):
    def test_append_sends_flags_and_ledgers_after_success(self):
        r = self.run_script('t1', *BASELINE, '--evidence-url', 'https://e.example/7')
        self.assertEqual(r.returncode, 0, r.stderr)
        appends = self.writes()
        self.assertEqual(len(appends), 1)
        for token in ('--minutes-per-unit 18', '--hourly-rate 60', '--currency USD',
                      '--provenance MEASURED', '--effective-from 2026-01-07T00:00:00Z',
                      '--evidence-url https://e.example/7'):
            self.assertIn(token, appends[0])
        self.assertNotIn('--dry-run', appends[0])
        self.assertNotIn('--cost-per-unit', appends[0])
        lines = self.ledger_lines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'^BASELINE:t1:[0-9a-f]{12}:\d+$')

    def test_effective_from_defaults_to_now(self):
        r = self.run_script('t1', '--minutes-per-unit', '5', '--provenance', 'MEASURED')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(self.writes()[0],
                         r'--effective-from \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')

    def test_rerun_is_refused_by_the_ledger_even_with_a_new_date(self):
        self.assertEqual(self.run_script('t1', *BASELINE).returncode, 0)
        later = [a if a != '2026-01-07T00:00:00Z' else '2026-02-01T00:00:00Z'
                 for a in BASELINE]
        r = self.run_script('t1', *later)
        self.assertEqual(r.returncode, 1)
        self.assertIn('already appended', r.stderr)
        self.assertEqual(len(self.writes()), 1)
        r = self.run_script('t1', *later, '--force')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.writes()), 2)
        self.assertEqual(len(self.ledger_lines()), 2)

    def test_identical_version_in_force_is_refused(self):
        self.env['STUB_LIST'] = json.dumps([{
            'minutesPerUnit': 18, 'hourlyRate': 60.0, 'currency': 'USD',
            'provenance': 'MEASURED', 'effectiveFrom': '2025-01-01T00:00:00Z'}])
        r = self.run_script('t1', *BASELINE)
        self.assertEqual(r.returncode, 1)
        self.assertIn('already declares these values', r.stderr)
        self.assertEqual(self.writes(), [])

    def test_a_changed_value_against_the_version_in_force_appends(self):
        self.env['STUB_LIST'] = json.dumps([{
            'minutesPerUnit': 20, 'hourlyRate': 60.0, 'currency': 'USD',
            'provenance': 'MEASURED'}])
        r = self.run_script('t1', *BASELINE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.writes()), 1)

    def test_unreadable_list_refuses_without_force(self):
        self.env['STUB_LIST'] = 'not json'
        r = self.run_script('t1', *BASELINE)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.writes(), [])

    def test_failed_append_writes_no_ledger_line(self):
        self.env['STUB_APPEND_FAIL'] = '1'
        r = self.run_script('t1', *BASELINE)
        self.assertEqual(r.returncode, 1)
        self.assertIn('failed', r.stderr)
        self.assertEqual(self.ledger_lines(), [])

    def test_dry_run_passes_dry_run_and_ledgers_nothing(self):
        r = self.run_script('t1', *BASELINE, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--dry-run', self.writes()[0])
        self.assertEqual(self.ledger_lines(), [])

    def test_cli_without_the_verb_is_detected_from_help_text(self):
        self.env['STUB_OLD_CLI'] = '1'
        r = self.run_script('t1', *BASELINE)
        self.assertEqual(r.returncode, 1)
        self.assertIn('upgrade the revenium CLI', r.stderr)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.ledger_lines(), [])


class OverheadTests(_Base):
    def test_overhead_round_trips_every_other_field(self):
        rule = {'ratePerUnit': 2.5, 'currency': 'EUR'}
        self.contract(monetization=rule)
        r = self.run_script('t1', '--overhead-per-unit', '0.4', '--overhead-currency', 'EUR')
        self.assertEqual(r.returncode, 0, r.stderr)
        sent = json.loads(Path(self.capture).read_text())
        self.assertEqual(sent['overheadPerUnit'], 0.4)
        self.assertEqual(sent['overheadCurrency'], 'EUR')
        self.assertEqual(sent['monetization'], rule)
        for k in ('dimensions', 'metrics', 'unitLabel', 'unitMetricKey'):
            self.assertEqual(sent[k], CONTRACT[k], k)
        self.assertNotIn('jobType', sent)
        self.assertNotIn('currentBaseline', sent)

    def test_overhead_never_adds_a_monetization_rule(self):
        self.contract()
        r = self.run_script('t1', '--overhead-per-unit', '1')
        self.assertEqual(r.returncode, 0, r.stderr)
        sent = json.loads(Path(self.capture).read_text())
        self.assertIsNone(sent['monetization'])
        self.assertEqual(sent['overheadCurrency'], 'USD')

    def test_overhead_currency_follows_currency(self):
        self.contract()
        r = self.run_script('t1', '--overhead-per-unit', '1', '--currency', 'GBP')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(Path(self.capture).read_text())['overheadCurrency'], 'GBP')

    def test_no_contract_refuses_and_appends_no_baseline(self):
        r = self.run_script('t1', '--overhead-per-unit', '1', *BASELINE)
        self.assertEqual(r.returncode, 1)
        self.assertIn('no economics contract', r.stderr)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.ledger_lines(), [])

    def test_overhead_dry_run_passes_dry_run(self):
        self.contract()
        r = self.run_script('t1', '--overhead-per-unit', '1', '--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--dry-run', [c for c in self.calls()
                                    if c.startswith('jobs types economics set')][0])


class NotInCronTests(unittest.TestCase):
    def test_never_named_by_the_per_tick_pipeline(self):
        for name in ('cron.sh', 'install-cron.sh'):
            text = (SKILL / 'scripts' / name).read_text()
            self.assertNotIn('declare-baseline', text, name)


if __name__ == '__main__':
    unittest.main()
