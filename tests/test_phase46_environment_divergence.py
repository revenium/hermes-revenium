"""Regression test for the PR #101 / Greptile finding on
`phase-46-safe-reporting-privacy-compatibility`: commit d2606f0 (CR-01)
clamped `source` to 64 bytes for the `--metadata` transport, but the SAME
`source_clean` pipe field also fed the in-loop `jobs create --environment`
flag (hermes-report.sh, in-loop stage around `jobs_cmd+=(--environment ...)`),
truncating a Revenium dimension that has no byte ceiling of its own and was
never supposed to be clamped.

This drives the REAL hermes-report.sh end to end (never a reimplementation
of its field selection — this repo has a documented six-time defect where
fixtures pin what the TEST produces, not what production sends) against a
custom `revenium` shim that fails the FIRST `jobs create` attempt (modeling
a transient API failure) and succeeds the second, forcing BOTH job-creation
call sites — the precheck stage (hermes-report.sh ~1516, already correct
pre- and post-fix) and the in-loop stage (hermes-report.sh ~2459, the
regressed site) — to each make a real, captured `revenium jobs create`
invocation for the SAME job id in one tick. Under the ledger-dedup gate
(`JOB:<id>:created:`), only a FAILED first attempt lets the second
(in-loop's own) call happen at all; a successful first attempt would make
the in-loop site's own invocation unreachable within a single tick and
this regression untestable end to end.

The in-loop attempt's success also lands the `JOB:<id>:created:` ledger
line before the post-loop outcome stage runs, so the SAME tick also ships
a real `revenium jobs outcome --metadata ...` call, letting this test prove
the required invariant in one real run:
  - `--environment` on BOTH `jobs create` call sites == the raw,
    unclamped session source (byte-identical, no 64-byte ceiling).
  - `--metadata`'s `source` key on the `jobs outcome` call == the SAME
    source, clamped to 64 serialized bytes.
"""
import json
import os
import shlex
import shutil
import tempfile
import unittest

from tests._compat_helpers import build_state_db, run_script, SCRIPTS_DIR

# A plain-ASCII, pipe/newline-free source well over the 64-byte --metadata
# clamp (103 chars == 103 serialized bytes for ASCII), so any accidental
# truncation is trivially visible as a shortened string.
_LONG_SOURCE = 'ENV-REGRESSION-SRC-' + 'Q' * 83
_JOB_ID = 'env-regression-job-001'


def _build_failonce_shim(shim_path, jobs_log, meter_log, counter_file):
    r"""Write a custom (non-build_shim) revenium stand-in.

    Deliberately NOT the shared `build_shim` helper (tests/_compat_helpers.py)
    -- that helper always exits 0 for every `jobs` subcommand, which makes
    the precheck stage's create call always succeed first and permanently
    shadows the in-loop stage's own call via the ledger-dedup gate. This
    shim instead fails the FIRST `jobs create --agentic-job-id <id>` call
    (no "409"/"already exist"/"conflict" in its output, so hermes-report.sh
    treats it as a real failure, not the idempotent-retry success case) and
    succeeds every subsequent call, so the in-loop stage's own invocation
    becomes observable in one real script run.
    """
    body = f"""#!/usr/bin/env bash
case "$1" in
  config) exit 0 ;;
  guardrails) exit 0 ;;
  meter)
    if [[ "$3" == "--help" ]]; then
      echo "--agentic-job-id  Agentic job instance identifier"
      exit 0
    fi
    printf "%q " "$@" >> "{meter_log}"
    printf "\\n" >> "{meter_log}"
    exit 0
    ;;
  jobs)
    if [[ "$2" == "--help" ]]; then exit 0; fi
    if [[ "$2" == "outcome" && "$3" == "--help" ]]; then
      echo "--outcome-value string     Business outcome value"
      echo "--outcome-currency string   Business outcome currency"
      exit 0
    fi
    # Log every real (non --help) jobs invocation -- create AND outcome.
    printf "%q " "$@" >> "{jobs_log}"
    printf "\\n" >> "{jobs_log}"
    if [[ "$2" == "create" ]]; then
      n=0
      [[ -f "{counter_file}" ]] && n=$(cat "{counter_file}")
      n=$((n + 1))
      echo "$n" > "{counter_file}"
      if [[ "$n" -eq 1 ]]; then
        echo "simulated transient jobs-create failure (attempt 1)" >&2
        exit 1
      fi
      exit 0
    fi
    exit 0
    ;;
  *) exit 0 ;;
esac
"""
    with open(shim_path, 'w') as f:
        f.write(body)
    os.chmod(shim_path, 0o755)


class EnvironmentMetadataDivergenceTests(unittest.TestCase):
    """Proves --environment stays raw on both jobs-create call sites while
    --metadata's source key stays clamped, driving the real script."""

    def test_environment_raw_on_both_paths_metadata_clamped_on_outcome(self):
        tmpdir = tempfile.mkdtemp(prefix='gsd-env-metadata-divergence-')
        try:
            hermes_home = os.path.join(tmpdir, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            os.makedirs(markers_dir, mode=0o700)
            state_db = os.path.join(hermes_home, 'state.db')

            shim_home = os.path.join(tmpdir, 'home')
            bin_dir = os.path.join(shim_home, '.local', 'bin')
            os.makedirs(bin_dir)
            meter_log = os.path.join(tmpdir, 'meter.log')
            jobs_log = os.path.join(tmpdir, 'jobs.log')
            inv_log = os.path.join(tmpdir, 'inv.log')
            counter_file = os.path.join(tmpdir, 'create_attempt_counter')
            shim = os.path.join(bin_dir, 'revenium')

            build_state_db(state_db, [{
                'id': 'env-div-sid-001',
                'model': 'claude-sonnet-4-6',
                'source': _LONG_SOURCE,
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

            # A standalone job marker (kind: job, terminal status) -- no task
            # marker needed; the WR-02 standalone job-only scan (precheck)
            # and the in-loop stage both read job rows straight off this file.
            job_marker = {
                'kind': 'job',
                'ts': 1715515101.0,
                'sid': 'env-div-sid-001',
                'agentic_job_id': _JOB_ID,
                'job_name': 'Environment Regression Job',
                'job_type': 'bug_fix',
                'status': 'SUCCESS',
            }
            with open(os.path.join(markers_dir, 'env-div-sid-001.jsonl'), 'w') as f:
                f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

            _build_failonce_shim(shim, jobs_log, meter_log, counter_file)

            base_env = {
                **os.environ,
                'HOME': shim_home,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
                'INVOCATIONS_LOG': inv_log,
                'METER_LOG': meter_log,
                'JOBS_LOG': jobs_log,
                'TZ': 'UTC',
                'REVENIUM_ORGANIZATION_NAME': '',
            }

            rc, _ignored, output = run_script(
                SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
            )
            self.assertEqual(
                rc, 0,
                f'hermes-report.sh failed (rc={rc}): {output}'
            )

            jobs_inv = []
            if os.path.exists(jobs_log):
                with open(jobs_log) as f:
                    for line in f:
                        line = line.rstrip('\n')
                        if line:
                            jobs_inv.append(shlex.split(line))

            create_invocations = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'create'
                and '--agentic-job-id' in a and _JOB_ID in a
            ]
            self.assertEqual(
                len(create_invocations), 2,
                f'expected exactly 2 "jobs create" attempts for {_JOB_ID} '
                f'(precheck fails, in-loop succeeds) -- got '
                f'{len(create_invocations)}\nFull jobs_log: {jobs_inv!r}\n'
                f'Output: {output}'
            )

            # Both the failed precheck attempt AND the succeeding in-loop
            # attempt must carry the RAW, unclamped source as --environment.
            for i, argv in enumerate(create_invocations):
                self.assertIn(
                    '--environment', argv,
                    f'jobs create attempt {i + 1} missing --environment: {argv!r}'
                )
                env_idx = argv.index('--environment')
                env_value = argv[env_idx + 1]
                self.assertEqual(
                    env_value, _LONG_SOURCE,
                    f'jobs create attempt {i + 1}: --environment was '
                    f'{env_value!r} ({len(env_value)} bytes), expected the '
                    f'RAW unclamped source {_LONG_SOURCE!r} '
                    f'({len(_LONG_SOURCE)} bytes) -- PR #101 regression: '
                    f'--environment must never be clamped'
                )

            # The outcome stage must have shipped exactly one `jobs outcome`
            # call this tick (create was confirmed by the in-loop attempt's
            # success before the post-loop outcome stage ran), and its
            # --metadata source key must be clamped to <= 64 serialized bytes
            # -- and strictly shorter than the raw source, proving the clamp
            # actually fired rather than merely not having anything to do.
            outcome_invocations = [
                a for a in jobs_inv
                if len(a) >= 2 and a[0] == 'jobs' and a[1] == 'outcome'
            ]
            self.assertEqual(
                len(outcome_invocations), 1,
                f'expected exactly 1 "jobs outcome" invocation -- got '
                f'{len(outcome_invocations)}\nFull jobs_log: {jobs_inv!r}\n'
                f'Output: {output}'
            )
            outcome_argv = outcome_invocations[0]
            self.assertIn(
                '--metadata', outcome_argv,
                f'jobs outcome missing --metadata: {outcome_argv!r}'
            )
            meta_idx = outcome_argv.index('--metadata')
            meta = json.loads(outcome_argv[meta_idx + 1])
            self.assertIn('source', meta, f'--metadata missing source key: {meta!r}')
            clamped_source = meta['source']
            self.assertLessEqual(
                len(clamped_source.encode('utf-8')), 64,
                f'--metadata source is {len(clamped_source.encode("utf-8"))} bytes, '
                f'over the 64-byte CR-01 clamp: {clamped_source!r}'
            )
            self.assertTrue(
                _LONG_SOURCE.startswith(clamped_source),
                f'clamped --metadata source {clamped_source!r} is not a prefix '
                f'of the raw source {_LONG_SOURCE!r}'
            )
            self.assertNotEqual(
                clamped_source, _LONG_SOURCE,
                'test setup invalid: --metadata source was not actually '
                'truncated -- the raw source must exceed 64 bytes'
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
