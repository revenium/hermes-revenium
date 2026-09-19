"""quick-260919: outcome-metrics-report.sh.

Three properties carry this script, and each has a failure mode that is
invisible at the moment it happens:

  * THE PROBE. 44 of 49 cobra parent commands exit 0 on an unknown
    subcommand and print the parent's help. An exit-status probe therefore
    reports "supported" on a CLI without the verb, we invoke it, help lands
    on stdout, exit is 0, and we ledger an append that never happened --
    then the ledger suppresses every retry. Silent, permanent data loss that
    looks like success.

  * IDEMPOTENCY. Appends are never deduplicated server-side, cannot be
    amended or deleted, and cannot be read back (OutcomeMetricEntry_Read has
    no producing endpoint). The ledger is the only thing preventing a retry
    from permanently doubling customer ROI data.

  * RANGE. The CLI bounds exactly one key, the literal `quality_rate`. Our
    SCORE metric is unchecked downstream, so a 0.7 -> 7.0 decimal slip would
    land permanently.

Every test drives the REAL script against a stub `revenium` placed under the
test's own HOME/.local/bin, per the recorded ensure_path isolation lesson --
a stub anywhere else lets the real binary shadow it.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPT = SKILL / 'scripts' / 'outcome-metrics-report.sh'


class _Base(unittest.TestCase):
    def _env(self, tmp, **over):
        hermes_home = os.path.join(tmp, 'hh')
        state_dir = os.path.join(hermes_home, 'state', 'revenium')
        os.makedirs(os.path.join(state_dir, 'job-assessments'), exist_ok=True)
        shim_home = os.path.join(tmp, 'home')
        bin_dir = os.path.join(shim_home, '.local', 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        env = {
            **os.environ,
            'HOME': shim_home,
            'HERMES_HOME': hermes_home,
            'REVENIUM_STATE_DIR': state_dir,
            'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'TZ': 'UTC',
        }
        env.update(over)
        return env, state_dir, bin_dir

    def _assessment(self, state_dir, job='job-1', job_type='t1',
                    value=70.0, hours=0.5, conf=0.7, status='reportable'):
        rec = {
            'kind': 'job_assessment', 'agentic_job_id': job, 'job_type': job_type,
            'reportability_status': status, 'estimated_value': value,
            'confidence': conf, 'assumptions': {'estimated_hours_saved': hours},
            'job_ended_at': 1789742045.0, 'ts': 1789742045.0, 'sequence': 0,
        }
        p = os.path.join(state_dir, 'job-assessments', f'{job}.jsonl')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + '\n')

    def _shim(self, bin_dir, *, has_verb=True, throttle=False, econ_404=True,
              log=None):
        """A stub `revenium`. `has_verb` controls whether `jobs --help` lists
        outcome-metrics; when it does NOT, the stub mimics cobra's real
        behaviour for an unknown subcommand: print the PARENT help, exit 0."""
        log = log or os.path.join(bin_dir, 'calls.log')
        verb_line = ('  outcome-metrics     Append late per-job outcome metrics\n'
                     if has_verb else '')
        body = f'''#!/bin/bash
echo "$*" >> "{log}"
if [ "$1" = "jobs" ] && [ "$2" = "--help" ]; then
  printf 'Manage Agentic Jobs\\n\\nAvailable Commands:\\n  create   Create\\n  outcome  Report\\n{verb_line}'
  exit 0
fi
if [ "$1" = "jobs" ] && [ "$2" = "types" ] && [ "$3" = "economics" ] && [ "$4" = "get" ]; then
  if [ "{throttle}" = "True" ]; then echo '{{"error":"x","status":429}}'; exit 1; fi
  if [ "{econ_404}" = "True" ]; then echo '{{"error":"Resource not found.","status":404}}'; exit 3; fi
  echo '{{"jobType":"t1","metrics":[]}}'; exit 0
fi
if [ "$1" = "jobs" ] && [ "$2" = "types" ] && [ "$3" = "economics" ] && [ "$4" = "set" ]; then
  echo "Contract"; exit 0
fi
if [ "$1" = "jobs" ] && [ "$2" = "outcome-metrics" ]; then
  if [ "{throttle}" = "True" ]; then echo '{{"error":"x","status":429}}'; exit 1; fi
  cat > /dev/null
  echo "Appended entries to job $3."; exit 0
fi
# Mimic cobra: unknown subcommand prints PARENT help and exits 0.
echo "Manage Agentic Jobs"; exit 0
'''
        p = os.path.join(bin_dir, 'revenium')
        Path(p).write_text(body)
        os.chmod(p, 0o755)
        return log

    def _run(self, env, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def _ledger(self, state_dir):
        p = os.path.join(state_dir, 'revenium-outcome-metrics.ledger')
        if not os.path.exists(p):
            return []
        return [l for l in Path(p).read_text().splitlines() if l.strip()]


class ProbeTests(_Base):
    def test_absent_verb_is_a_noop_and_ledgers_nothing(self):
        """THE phantom-success guard.

        The stub mimics cobra exactly: `jobs outcome-metrics` prints the
        parent help and exits 0. If the script probed exit status it would
        read that as a successful append and write ledger lines for data that
        never left the host -- and the ledger would then suppress the retry
        forever.
        """
        with tempfile.TemporaryDirectory(prefix='gsd-om-noverb-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=False)
            self._assessment(state_dir)
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual(
                [], self._ledger(state_dir),
                'a CLI without the verb must ledger NOTHING; a line here means '
                'we recorded an append that never happened',
            )
            calls = Path(log).read_text() if os.path.exists(log) else ''
            self.assertNotIn(
                'outcome-metrics', calls.replace('jobs --help', ''),
                'the verb must never be invoked when the probe says absent',
            )

    def test_present_verb_appends_and_ledgers(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-verb-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            led = self._ledger(state_dir)
            self.assertEqual(4, len(led), f'expected 4 metric lines, got {led}')
            self.assertTrue(all(l.startswith('OM:job-1:') for l in led), led)


class IdempotencyTests(_Base):
    def test_second_run_appends_nothing(self):
        """The property protecting against permanent double-billing."""
        with tempfile.TemporaryDirectory(prefix='gsd-om-idem-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)

            self._run(env)
            first = self._ledger(state_dir)
            appends_1 = Path(log).read_text().count('outcome-metrics')

            self._run(env)
            second = self._ledger(state_dir)
            appends_2 = Path(log).read_text().count('outcome-metrics')

            self.assertEqual(first, second, 'ledger must not grow on a re-run')
            self.assertEqual(
                appends_1, appends_2,
                'the second run must issue NO new append; appends are permanent, '
                'never deduplicated server-side, and cannot be read back or deleted',
            )

    def test_throttled_append_is_not_ledgered(self):
        """429 must defer, so the next tick retries rather than losing data."""
        with tempfile.TemporaryDirectory(prefix='gsd-om-429-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True, throttle=True, econ_404=False)
            self._assessment(state_dir)
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual(
                [], self._ledger(state_dir),
                'a throttled append must leave no ledger line, or the retry is '
                'suppressed and the metric is lost',
            )


class RangeValidationTests(_Base):
    def test_out_of_range_score_is_refused_before_any_append(self):
        """The decimal slip the CLI cannot catch.

        The CLI bounds only the literal key `quality_rate`; our SCORE metric
        is unchecked downstream, and the append is permanent.
        """
        with tempfile.TemporaryDirectory(prefix='gsd-om-range-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir, conf=7.0)   # 0.7 slipped to 7.0
            r = self._run(env)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual(
                [], self._ledger(state_dir),
                'an out-of-range SCORE must block the whole job',
            )
            calls = Path(log).read_text() if os.path.exists(log) else ''
            self.assertNotIn(
                'jobs outcome-metrics', calls,
                'nothing may be appended for a job with an out-of-range value: a '
                'partial append is still permanent',
            )

    def test_negative_money_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-neg-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir, value=-5.0)
            self._run(env)
            self.assertEqual([], self._ledger(state_dir))

    def test_boundary_values_are_accepted(self):
        """0 and 1 are legal for SCORE -- inclusive at both ends."""
        with tempfile.TemporaryDirectory(prefix='gsd-om-bound-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir, conf=1.0, hours=0.0)
            self._run(env)
            self.assertTrue(
                self._ledger(state_dir),
                'confidence exactly 1.0 and hours exactly 0 are in range and '
                'must not be refused',
            )


class SelectionTests(_Base):
    def test_non_reportable_assessments_are_skipped(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-cand-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir, job='cand', status='candidate')
            self._run(env)
            self.assertEqual(
                [], self._ledger(state_dir),
                'an abstained assessment claims no value and must not be shipped',
            )

    def test_max_jobs_zero_disables_the_stage(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-off-') as tmp:
            env, state_dir, bin_dir = self._env(
                tmp, REVENIUM_OUTCOME_METRICS_MAX_JOBS='0')
            self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)
            self._run(env)
            self.assertEqual([], self._ledger(state_dir))

    def test_max_jobs_bounds_the_tick(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-cap-') as tmp:
            env, state_dir, bin_dir = self._env(
                tmp, REVENIUM_OUTCOME_METRICS_MAX_JOBS='2')
            self._shim(bin_dir, has_verb=True)
            for i in range(5):
                self._assessment(state_dir, job=f'job-{i}')
            self._run(env)
            jobs = {l.split(':')[1] for l in self._ledger(state_dir)}
            self.assertEqual(
                2, len(jobs), f'expected 2 jobs capped per tick, got {jobs}')

    def test_dry_run_appends_nothing(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-dry-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=True)
            self._assessment(state_dir)
            self._run(env, '--dry-run')
            self.assertEqual([], self._ledger(state_dir))
            calls = Path(log).read_text() if os.path.exists(log) else ''
            self.assertNotIn('jobs outcome-metrics', calls)


class EconomicsTests(_Base):
    def test_contract_is_created_only_on_404_and_never_with_yes(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-econ-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=True, econ_404=True)
            self._assessment(state_dir)
            self._run(env)
            calls = Path(log).read_text()
            self.assertIn('economics set', calls, 'a 404 type must get a contract')
            self.assertNotIn(
                '--yes', calls,
                'never pass --yes from an unattended run: a --yes demand means a '
                'contract exists and our document would destroy part of it',
            )

    def test_existing_contract_is_left_alone(self):
        with tempfile.TemporaryDirectory(prefix='gsd-om-econ2-') as tmp:
            env, state_dir, bin_dir = self._env(tmp)
            log = self._shim(bin_dir, has_verb=True, econ_404=False)
            self._assessment(state_dir)
            self._run(env)
            calls = Path(log).read_text()
            self.assertNotIn(
                'economics set', calls,
                'an operator-tuned contract must never be replaced by cron',
            )


if __name__ == '__main__':
    unittest.main()
