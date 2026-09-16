"""PR #124: `--organization-name` is capability-probed PER SUBCOMMAND.

The production incident this pins: `--organization-name` is accepted by
`revenium meter completion` and REJECTED by `revenium jobs create`. Verified
against the live CLI 1.5.0 on the fleet host 2026-09-16 --

    meter completion --help  -> rc=0, 10379 bytes, advertises the flag
    jobs create --help       -> rc=0,  2133 bytes, does NOT
    jobs outcome --help      -> rc=0,  2376 bytes, does NOT

and a real `jobs create --agentic-job-id ... --organization-name X` answers
`Error: unknown flag: --organization-name`, exit 1. Because the reporter
creates the job BEFORE metering its completions, one unsupported flag on the
jobs path took job creation down fleet-wide for ~41h while completions kept
flowing -- and it stayed latent until an operator first set `organizationName`,
since an unset value appends nothing and looks healthy.

So the distinction under test is not "does the flag ship" but "is each
subcommand probed on ITS OWN help". A single probe of `meter completion` whose
answer is reused on the jobs path passes every pre-existing test in this repo
and reproduces the incident exactly.

Both cases below run with a NON-EMPTY organizationName -- the empty-string
default every other jobs test uses cannot distinguish "correctly gated" from
"never appended".
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import (
    argv_to_flags,
    build_shim,
    build_state_db,
    run_script,
    SCRIPTS_DIR,
)

_ORG = 'TableForOne Games'
_JOB_ID = 'orgflag-job-001'
_SID = 'orgflag-sid-001'


class JobsOrgNameCapabilityTests(unittest.TestCase):
    def _run(self, jobs_org_capable):
        """Run hermes-report.sh once against a shim whose `jobs create --help`
        advertises --organization-name iff jobs_org_capable.

        Returns (jobs_create_argv_flags, meter_completion_argv_flags).
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-jobs-orgflag-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            # ORG_NAME is read from config.json's organizationName
            # (hermes-report.sh:276-278), not from the environment.
            with open(os.path.join(state_dir, 'config.json'), 'w') as f:
                json.dump({'organizationName': _ORG}, f)

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')

            # started_at far in the past so the session clears the settle gate
            # without a .ready sentinel.
            build_state_db(state_db, [{
                'id': _SID,
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': '0',
                'api_calls': 1,
                'started_at': 1715514000.0,
                'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
            }])

            task_marker = {
                'muid': 'orgflag-task-001',
                'ts': 1715515100.5,
                'sid': _SID,
                'task_type': 'code_review',
                'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job',
                'ts': 1715515101.0,
                'sid': _SID,
                'agentic_job_id': _JOB_ID,
                'job_name': 'Org Flag Job',
                'job_type': 'code_review',
                'status': 'IN_PROGRESS',
            }
            with open(os.path.join(markers_dir, f'{_SID}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            build_shim(os.path.join(bin_dir, 'revenium'),
                       jobs_org_capable=jobs_org_capable)

            env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
            }

            rc, _inv, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', env, inv_log
            )
            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')

            def _argvs(path):
                out = []
                if os.path.exists(path):
                    with open(path) as f:
                        for line in f:
                            line = line.rstrip('\n')
                            if line:
                                out.append(shlex.split(line))
                return out

            creates = [a for a in _argvs(jobs_log)
                       if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create']
            self.assertEqual(
                len(creates), 1,
                f'expected exactly one `jobs create`, got {creates!r}\n{output}'
            )
            # A --help probe reaching the capture would mean the shim is
            # modelling the CLI wrong, not that the reporter is misbehaving.
            self.assertNotIn(
                '--help', creates[0],
                f'a capability probe was captured as a real jobs create: {creates[0]!r}'
            )

            meters = [a for a in _argvs(meter_log)
                      if len(a) >= 2 and a[0] == 'meter' and a[1] == 'completion']
            self.assertGreaterEqual(
                len(meters), 1,
                f'expected at least one `meter completion`, got {meters!r}\n{output}'
            )
            return argv_to_flags(creates[0]), argv_to_flags(meters[0])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_jobs_create_omits_org_name_when_its_own_help_lacks_it(self):
        """The shipping-CLI shape, and the incident's exact shape.

        `meter completion` advertises the flag and carries it; `jobs create`
        does not advertise it and must omit it even though organizationName is
        set. Reusing the metering probe's answer here is what broke jobs
        creation fleet-wide.
        """
        create_flags, meter_flags = self._run(jobs_org_capable=False)

        self.assertNotIn(
            '--organization-name', create_flags,
            'jobs create carried --organization-name although its own --help '
            'does not advertise it -- the CLI rejects this outright '
            '("unknown flag"), failing job creation for the whole fleet'
        )
        self.assertEqual(
            meter_flags.get('--organization-name'), _ORG,
            'meter completion lost --organization-name; the jobs-path gate '
            'must not suppress the ORGANIZATION dimension where it IS supported'
        )

    def test_jobs_create_carries_org_name_when_its_own_help_advertises_it(self):
        """The forward-compatible shape: a CLI that accepts the flag on the
        jobs path gets it, so a job and its transactions land in one org."""
        create_flags, meter_flags = self._run(jobs_org_capable=True)

        self.assertEqual(
            create_flags.get('--organization-name'), _ORG,
            'jobs create omitted --organization-name although its own --help '
            'advertises it -- the job would land in a different organization '
            'than its own transactions'
        )
        self.assertEqual(
            meter_flags.get('--organization-name'), _ORG,
            'meter completion lost --organization-name'
        )


if __name__ == '__main__':
    unittest.main()
