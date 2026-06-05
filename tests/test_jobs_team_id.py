"""quick-260605: teamId resolution + explicit --team-id passing on job calls.

Root cause fixed here: `revenium jobs create` requires teamId. When the global
`revenium config` lacks it, the CLI returns HTTP 400 / exit 4, the cron's
409-only success check treats it as a generic failure, no JOB:created ledger
line is written, and the outcome is deferred forever (jobs land in Revenium
with hasOutcome=false). hermes-report.sh now resolves teamId (env override ->
`revenium config show`) and passes --team-id explicitly on jobs create/outcome,
warning loudly when it cannot be resolved.

These tests use bespoke shims (not _compat_helpers.build_shim, whose `config`
branch is a no-op) so `revenium config show` can return a Team ID.
"""
import json
import os
import shlex
import shutil
import stat
import tempfile
import unittest

from tests._compat_helpers import build_state_db, run_script, SCRIPTS_DIR


def _write_shim(path, *, team_id_line):
    """Write a revenium shim. `team_id_line` is the literal line emitted by
    `revenium config show` for the team (pass '' to omit it)."""
    config_show = 'echo "api_key: mock"\n'
    if team_id_line:
        config_show += f'      echo "{team_id_line}"\n'
    body = (
        '#!/usr/bin/env bash\n'
        'case "$1" in\n'
        '  config)\n'
        '    if [[ "$2" == "show" ]]; then\n'
        f'      {config_show}'
        '    fi\n'
        '    exit 0 ;;\n'
        '  guardrails) exit 0 ;;\n'
        '  meter)\n'
        '    if [[ "$3" == "--help" ]]; then echo "--agentic-job-id  id"; exit 0; fi\n'
        '    exit 0 ;;\n'
        '  jobs)\n'
        '    if [[ "$2" == "--help" ]]; then exit 0; fi\n'
        '    printf "%q " "$@" >> "${JOBS_LOG:-/dev/null}"\n'
        '    printf "\\n"      >> "${JOBS_LOG:-/dev/null}"\n'
        '    exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
    )
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, 0o755)


class TestJobsTeamId(unittest.TestCase):
    def _run(self, *, team_id_line):
        tmpdir = tempfile.mkdtemp(prefix='gsd-team-id-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            _write_shim(os.path.join(bin_dir, 'revenium'), team_id_line=team_id_line)

            sid = 'team-sid-001'
            job_id = 'team-job-001'
            build_state_db(state_db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'cli',
                'input_tokens': 100, 'output_tokens': 50, 'cache_read': 0,
                'cache_write': 0, 'reasoning': 0, 'estimated_cost': '0',
                'api_calls': 1, 'started_at': 1715514000.0,
                'ended_at': 1715514000.0, 'billing_provider': 'anthropic',
            }])
            task_marker = {
                'muid': 'team-task-001', 'ts': 1715516000.5, 'sid': sid,
                'task_type': 'code_review', 'operation_type': 'CHAT',
            }
            job_marker = {
                'kind': 'job', 'ts': 1715516002.0, 'sid': sid,
                'agentic_job_id': job_id, 'job_name': 'Team Test Job',
                'job_type': 'testing', 'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
                f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
            }
            # Ensure no ambient override leaks in from the runner's environment.
            base_env.pop('REVENIUM_TEAM_ID', None)

            rc, _ig, output = run_script(SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log)
            self.assertEqual(rc, 0, f'hermes-report.sh failed rc={rc}: {output}')
            # warn() tees to the metering log; fold it into output for assertions.
            log_path = os.path.join(state_dir, 'revenium-metering.log')
            if os.path.exists(log_path):
                with open(log_path) as lf:
                    output += '\n' + lf.read()

            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as fh:
                    for line in fh:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))
            return jobs_inv, output
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _flag_value(argv, flag):
        for i, tok in enumerate(argv):
            if tok == flag and i + 1 < len(argv):
                return argv[i + 1]
        return None

    def test_team_id_passed_on_create_and_outcome(self):
        jobs_inv, output = self._run(team_id_line='Team ID: team-xyz')
        creates = [a for a in jobs_inv if len(a) >= 2 and a[:2] == ['jobs', 'create']]
        outcomes = [a for a in jobs_inv if len(a) >= 2 and a[:2] == ['jobs', 'outcome']]
        self.assertTrue(creates, f'expected a jobs create invocation: {jobs_inv!r}\n{output}')
        self.assertTrue(outcomes, f'expected a jobs outcome invocation: {jobs_inv!r}\n{output}')
        for a in creates:
            self.assertEqual(self._flag_value(a, '--team-id'), 'team-xyz',
                             f'create missing --team-id: {a!r}')
        for a in outcomes:
            self.assertEqual(self._flag_value(a, '--team-id'), 'team-xyz',
                             f'outcome missing --team-id: {a!r}')

    def test_warn_and_no_team_flag_when_unresolved(self):
        jobs_inv, output = self._run(team_id_line='')
        # Loud, diagnosable warn instead of silent failure.
        self.assertIn('teamId not configured', output,
                      f'expected loud teamId warn in output:\n{output}')
        # With no resolved team-id, the flag is omitted (v1.4 wire shape preserved).
        for a in jobs_inv:
            self.assertIsNone(self._flag_value(a, '--team-id'),
                              f'--team-id must be omitted when unresolved: {a!r}')


if __name__ == '__main__':
    unittest.main()
