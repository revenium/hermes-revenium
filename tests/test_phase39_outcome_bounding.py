"""Phase 39 Plan 02 -- bound the deferred/wedged job-outcome logger.

`hermes-report.sh`'s post-loop outcome stage (the OUTCOME-04 gate at
`:2840-2855`) re-logs a deferred or wedged job on EVERY cron tick with no
sentinel. A job whose `jobs create` never confirms therefore logs forever --
the same unbounded-per-tick shape as the incident recorded in
`common.sh:27-32` (9,039,937 lines fleet-wide, 98.2% of one 646 MB log, in 27
days), just a smaller population. D-02 (39-CONTEXT.md) puts the fix in scope
for this phase.

**Log-across-ticks decision (required by the plan's Task 1 `<action>`):**
`tests/test_phase38_reporter_path.py`'s `_run_tick` (`:573-583`) deletes
`revenium-metering.log` before every tick, which would make a "one line
after two ticks" assertion pass against the BROKEN (unbounded) design just
as easily as the fixed one -- tick 2's freshly-emptied log holds exactly one
line either way, because deleting the log resets the count to zero every
single tick regardless of whether the sentinel gate matches. This file's
`_run_tick` therefore does the OPPOSITE: it never deletes
`revenium-metering.log` between ticks. Suppression is proven by reading the
WHOLE file after N ticks and asserting the deferred/wedged line count does
not grow past 1 -- a per-tick-keyed sentinel (the `unknown-<epoch>` shape
`pre_llm_call.sh:73-115` already paid for once) fails this assertion because
it leaves N lines, one per tick. Row 2 below is the companion control: a
directory listing of the new sentinel directory after two ticks, which is
the one assertion a per-tick key cannot survive even if a log-count
assertion were somehow measured wrong.

Requirements covered: ROI-14 (the rate-limit clause read honestly, per D-02).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests._compat_helpers import ROOT, SCRIPTS_DIR, build_state_db
from tests.test_phase38_reporter_path import _build_flexible_shim

COMMON_SH = SCRIPTS_DIR / 'common.sh'
HERMES_REPORT = SCRIPTS_DIR / 'hermes-report.sh'
PRUNE_MARKERS = SCRIPTS_DIR / 'prune-markers.sh'


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _setup(sid, job_id, marker_ts=None, seed_created=False, seed_outcome=False,
           extra_env=None):
    """One token-bearing session in state.db, a marker file carrying a
    kind:"job" line with status SUCCESS and an agentic_job_id, and a
    `revenium` shim (reused from test_phase38_reporter_path's
    _build_flexible_shim) whose jobs-create/jobs-outcome exit codes are
    controlled per-tick via JOBS_CREATE_EXIT_CODE / OUTCOME_EXIT_CODE. The
    jobs ledger starts EMPTY unless seed_created/seed_outcome request
    otherwise, so the OUTCOME-04 branch at hermes-report.sh:2840 fires by
    default (JOBS_CREATE_EXIT_CODE defaults to '1' -- create never
    confirms).

    Stubs live under a redirected HOME/.local/bin (never the bare PATH) per
    the recorded ensure_path isolation lesson -- a shim anywhere else is
    shadowed by the real binary, which for a real `revenium` CLI would leak
    a live network call out of a unit test.

    The HERMES completions ledger is pre-seeded with a row whose total_tokens
    already equals the session's (150 = 100 + 50): hermes-report.sh pushes a
    job into job_outcome_queue from TWO independent producers in one loop
    iteration -- a token-independent marker precheck that runs unconditionally
    (`:1339-1345`, "additive only", by design), and the in-loop jobs-create
    stage gated on the token-growth check (`:1877-1879`). A first-ever
    (zero-baseline) session clears both, so it is queued TWICE in the SAME
    tick, and the OUTCOME-04 branch would legitimately fire twice per tick
    for one job even under a correct per-(outcome_id, reason) sentinel (the
    second push's flag check finds the first push's flag already written
    this same tick and is silently absorbed -- correct, but it makes the
    backlog COUNT ambiguous for this fixture's purposes). Seeding the ledger
    with a matching total makes the session token-stable, which trips the
    growth-guard `continue` at `:1877-1879` and skips the in-loop stage
    entirely -- leaving the token-independent precheck as the SOLE producer,
    so this fixture's job is queued exactly once per tick, and "one line /
    one flag file" means what it says.
    """
    tmpdir = tempfile.mkdtemp(prefix='gsd-phase39-outcome-')
    hermes_home = os.path.join(tmpdir, 'hh')
    state_dir = os.path.join(hermes_home, 'state', 'revenium')
    markers_dir = os.path.join(state_dir, 'markers')
    os.makedirs(markers_dir, mode=0o700)
    state_db = os.path.join(hermes_home, 'state.db')
    jobs_ledger = os.path.join(state_dir, 'revenium-jobs.ledger')
    hermes_ledger = os.path.join(state_dir, 'revenium-hermes.ledger')

    shim_home = os.path.join(tmpdir, 'home')
    bin_dir = os.path.join(shim_home, '.local', 'bin')
    os.makedirs(bin_dir)
    shim = os.path.join(bin_dir, 'revenium')
    _build_flexible_shim(shim)

    now = time.time()
    input_tokens, output_tokens = 100, 50
    build_state_db(state_db, [{
        'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'test',
        'input_tokens': input_tokens, 'output_tokens': output_tokens,
        'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
        'estimated_cost': '0', 'api_calls': 1,
        'started_at': now - 120, 'ended_at': now - 60,
        'billing_provider': 'anthropic',
    }])

    # Token-stable seed row -- see the docstring's "single producer" note.
    with open(hermes_ledger, 'w') as f:
        f.write(
            f'HERMES:{sid}:{input_tokens + output_tokens}:{now - 90:.3f}:seed-muid\n'
        )

    ts = marker_ts if marker_ts is not None else now
    task_marker = {
        'muid': f'{job_id}-task', 'ts': ts, 'sid': sid,
        'task_type': 'code_review', 'operation_type': 'CHAT',
    }
    job_marker = {
        'kind': 'job', 'ts': ts, 'sid': sid,
        'agentic_job_id': job_id, 'job_name': 'Phase 39 Outcome Bounding Test',
        'job_type': 'code_review', 'status': 'SUCCESS',
    }
    with open(os.path.join(markers_dir, f'{sid}.jsonl'), 'w') as f:
        f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
        f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

    if seed_created or seed_outcome:
        with open(jobs_ledger, 'w') as f:
            f.write(f'JOB:{job_id}:created:{ts + 1:.3f}\n')
            if seed_outcome:
                f.write(f'JOB:{job_id}:outcome:{ts + 2:.3f}:SUCCESS\n')

    meter_log = os.path.join(tmpdir, 'meter.log')
    jobs_log = os.path.join(tmpdir, 'jobs.log')
    open(meter_log, 'w').close()
    open(jobs_log, 'w').close()

    env = {
        **os.environ,
        'HOME': shim_home,
        'HERMES_HOME': hermes_home,
        'REVENIUM_STATE_DIR': state_dir,
        'PATH': bin_dir + os.pathsep + os.environ.get('PATH', ''),
        'METER_LOG': meter_log,
        'JOBS_LOG': jobs_log,
        'TZ': 'UTC',
        'REVENIUM_ORGANIZATION_NAME': '',
        'JOBS_CREATE_EXIT_CODE': '1',
        # The session's age (60s, from started_at/ended_at above) must clear
        # the settle-sentinel gate (BUG-1) or the session is deferred before
        # the outcome stage ever runs at all -- unrelated to the OUTCOME-04
        # gate this file targets. No .ready sentinel is written, so the
        # age-fallback path is what must clear it.
        'REVENIUM_CRON_SETTLE_SECONDS': '1',
    }
    if extra_env:
        env.update(extra_env)
    return tmpdir, state_dir, markers_dir, jobs_ledger, meter_log, jobs_log, env


def _run_tick(env):
    """Run hermes-report.sh once. Deliberately does NOT delete
    revenium-metering.log between ticks -- see the module docstring for why
    that is the load-bearing choice this file makes differently from
    tests/test_phase38_reporter_path.py's _run_tick."""
    result = subprocess.run(
        ['bash', str(HERMES_REPORT)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


def _metering_log_text(state_dir):
    path = os.path.join(state_dir, 'revenium-metering.log')
    return Path(path).read_text() if os.path.exists(path) else ''


def _deferred_or_wedged_lines(text):
    return [
        l for l in text.splitlines()
        if 'outcome deferred:' in l or 'wedged job' in l
    ]


def _jobs_calls(jobs_log, verb):
    """Parse JOBS_LOG (NO-SHIFT argv, one shell-escaped invocation per line,
    first token 'jobs') and filter to the given subcommand."""
    import shlex
    calls = []
    if not os.path.exists(jobs_log):
        return calls
    with open(jobs_log) as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            argv = shlex.split(line)
            if len(argv) >= 2 and argv[0] == 'jobs' and argv[1] == verb:
                calls.append(argv)
    return calls


# ---------------------------------------------------------------------------
# Rows 1-6: cross-tick behaviour of the OUTCOME-04 branch
# ---------------------------------------------------------------------------

class OutcomeBoundingCrossTickTests(unittest.TestCase):

    def test_row1_suppression_across_ticks(self):
        """Row 1: tick 1 emits exactly one per-job deferred line; tick 2,
        same state dir, emits ZERO new ones."""
        tmpdir, state_dir, *_rest, env = _setup('p39-sup-sid', 'p39-sup-job')
        try:
            rc1, out1 = _run_tick(env)
            self.assertEqual(rc1, 0, out1)
            log1 = _metering_log_text(state_dir)
            self.assertEqual(len(_deferred_or_wedged_lines(log1)), 1, log1)

            rc2, out2 = _run_tick(env)
            self.assertEqual(rc2, 0, out2)
            log2 = _metering_log_text(state_dir)
            new_text = log2[len(log1):]
            self.assertEqual(
                len(_deferred_or_wedged_lines(new_text)), 0,
                f'tick 2 must add ZERO new deferred/wedged lines:\n{new_text}',
            )
            self.assertEqual(
                len(_deferred_or_wedged_lines(log2)), 1,
                f'exactly one deferred/wedged line must exist across both ticks:\n{log2}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row2_exactly_one_flag_file_after_two_ticks(self):
        """Row 2: the control. A stable (outcome_id, reason) key leaves
        exactly one file in OUTCOME_WARN_FLAGS_DIR after two ticks; a
        per-tick key (the unknown-<epoch> shape) would leave two. This row
        catches a defeated gate that row 1 alone could pass if row 1 were
        ever measured against a truncated/reset log."""
        tmpdir, state_dir, markers_dir, *_rest, env = _setup(
            'p39-flagcount-sid', 'p39-flagcount-job',
        )
        try:
            rc1, out1 = _run_tick(env)
            self.assertEqual(rc1, 0, out1)
            rc2, out2 = _run_tick(env)
            self.assertEqual(rc2, 0, out2)

            flag_dir = os.path.join(markers_dir, '.outcome-warn')
            self.assertTrue(os.path.isdir(flag_dir), f'{flag_dir} must exist after a deferred tick')
            files = [
                f for f in os.listdir(flag_dir)
                if os.path.isfile(os.path.join(flag_dir, f))
            ]
            self.assertEqual(
                len(files), 1,
                f'a stable (outcome_id, reason) key must leave exactly ONE flag '
                f'file after two ticks -- a per-tick key leaves one per tick: {files}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row3_reason_transition_fires_exactly_one_further_line(self):
        """Row 3: with REVENIUM_JOBS_STALE_SECONDS lowered so the (unchanged)
        marker ts crosses the threshold on tick 2, the wedged line fires
        exactly once more, and the deferred reason does not re-fire. A
        transition is the informative event -- mirrors
        FallbackWarnBoundingTests.test_reason_transition_warns_again.

        A third tick at the SAME (now-lowered) threshold is required to make
        this row RED against the unmodified script: reason SELECTION
        (deferred vs wedged) is pre-existing, threshold-driven branching
        that already alternates correctly with no sentinel at all -- ticks 1
        and 2 alone would pass unmodified. Only a same-reason repeat (tick 3
        must add ZERO further wedged lines) exercises the suppression this
        plan adds."""
        tmpdir, state_dir, *_rest, env = _setup('p39-trans-sid', 'p39-trans-job')
        try:
            rc1, out1 = _run_tick(env)
            self.assertEqual(rc1, 0, out1)
            log1 = _metering_log_text(state_dir)
            self.assertIn('outcome deferred:', log1, log1)
            self.assertNotIn('wedged job', log1, log1)

            env2 = {**env, 'REVENIUM_JOBS_STALE_SECONDS': '0'}
            rc2, out2 = _run_tick(env2)
            self.assertEqual(rc2, 0, out2)
            log2 = _metering_log_text(state_dir)
            new_text_2 = log2[len(log1):]
            self.assertIn(
                'wedged job', new_text_2,
                f'the reason transition must fire exactly one further line:\n{new_text_2}',
            )
            self.assertNotIn(
                'outcome deferred:', new_text_2,
                f'the OLD (deferred) reason must not re-fire on the transition tick:\n{new_text_2}',
            )

            rc3, out3 = _run_tick(env2)
            self.assertEqual(rc3, 0, out3)
            log3 = _metering_log_text(state_dir)
            new_text_3 = log3[len(log2):]
            self.assertNotIn(
                'wedged job', new_text_3,
                f'the SAME (wedged) reason must not re-fire on tick 3, once already '
                f'warned on tick 2:\n{new_text_3}',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row4_retry_survives_the_suppression_gate(self):
        """Row 4: flip the shim to JOBS_CREATE_EXIT_CODE=0 on a later tick
        against the same state dir and assert the job creates and its
        outcome ships. The gate is on the LINE, never on the `continue` --
        a job that stops being retried is a job that never reports."""
        tmpdir, state_dir, markers_dir, jobs_ledger, meter_log, jobs_log, env = _setup(
            'p39-retry-sid', 'p39-retry-job',
        )
        try:
            rc1, out1 = _run_tick(env)
            self.assertEqual(rc1, 0, out1)
            self.assertEqual(
                len(_jobs_calls(jobs_log, 'outcome')), 0,
                'tick 1 (create fails) must ship no outcome',
            )
            self.assertFalse(
                os.path.exists(jobs_ledger) and 'created:' in Path(jobs_ledger).read_text(),
                'no created line should exist after tick 1s failed create',
            )

            # Isolate tick 2's own argv -- these are argv-capture logs, not
            # the aggregate metering log the suppression gate protects, so
            # truncating them between ticks is safe and keeps this row's
            # assertion about tick 2 precise.
            open(jobs_log, 'w').close()
            env2 = {**env, 'JOBS_CREATE_EXIT_CODE': '0'}
            rc2, out2 = _run_tick(env2)
            self.assertEqual(rc2, 0, out2)

            create_calls = _jobs_calls(jobs_log, 'create')
            outcome_calls = _jobs_calls(jobs_log, 'outcome')
            self.assertEqual(
                len(create_calls), 1,
                f'tick 2 must attempt the create exactly once: {create_calls}',
            )
            self.assertEqual(
                len(outcome_calls), 1,
                f'tick 2 must ship the now-confirmed outcome exactly once: {outcome_calls}',
            )
            ledger_text = Path(jobs_ledger).read_text()
            self.assertTrue(
                'created:' in ledger_text,
                'jobs ledger must carry the created line after tick 2',
            )
            self.assertTrue(
                'outcome:' in ledger_text,
                'jobs ledger must carry the outcome line after tick 2',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row5_nonzero_backlog_emits_exactly_one_aggregate_line(self):
        """Row 5: a tick with a non-zero deferred/wedged backlog emits
        exactly one aggregate line."""
        tmpdir, state_dir, *_rest, env = _setup('p39-agg-nonzero-sid', 'p39-agg-nonzero-job')
        try:
            rc, out = _run_tick(env)
            self.assertEqual(rc, 0, out)
            log_text = _metering_log_text(state_dir)
            agg_lines = [
                l for l in log_text.splitlines()
                if re.search(r'outcome backlog: \d+ job', l)
            ]
            self.assertEqual(len(agg_lines), 1, log_text)
            self.assertIn(' 1 job', agg_lines[0])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row6_zero_backlog_emits_no_aggregate_line(self):
        """Row 6: a tick whose only job has a confirmed create AND an
        already-written outcome ledger line (OUTCOME-01 skips before
        OUTCOME-04 ever runs) emits no aggregate line at all."""
        tmpdir, state_dir, *_rest, env = _setup(
            'p39-agg-zero-sid', 'p39-agg-zero-job',
            seed_created=True, seed_outcome=True,
        )
        try:
            rc, out = _run_tick(env)
            self.assertEqual(rc, 0, out)
            log_text = _metering_log_text(state_dir)
            self.assertNotIn('outcome backlog:', log_text, log_text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_row7_growing_session_double_push_dedupes_backlog_aggregate(self):
        """WR-01 regression (39-REVIEW.md): a session whose token total is
        STILL GROWING this tick clears BOTH job_outcome_queue producers --
        the token-independent marker precheck (`:1473`) AND the in-loop
        jobs-create stage (`:2375`, gated on the growth guard at `:1884`
        which this fixture deliberately does NOT trip) -- pushing the SAME
        outcome_id into the queue twice in one tick.

        The per-job WARN line and the retry are already correctly
        deduplicated by the (outcome_id, reason) flag file (row 1). This
        test proves the post-loop AGGREGATE ('outcome backlog: N job(s)...')
        reports the DISTINCT job count (1), not the raw queue-entry count
        (2) the double push would otherwise produce.

        Unlike `_setup`'s default fixture -- which deliberately seeds the
        HERMES ledger with a token-STABLE row so the growth guard trips and
        the in-loop stage never runs, per `_setup`'s own docstring -- this
        test overwrites the ledger with a LOWER prior total so the growth
        guard does NOT trip and both producers fire.
        """
        tmpdir, state_dir, markers_dir, jobs_ledger, meter_log, jobs_log, env = _setup(
            'p39-double-sid', 'p39-double-job',
        )
        try:
            hermes_ledger = os.path.join(state_dir, 'revenium-hermes.ledger')
            now = time.time()
            with open(hermes_ledger, 'w') as f:
                f.write(f'HERMES:p39-double-sid:100:{now - 90:.3f}:seed-muid\n')

            rc, out = _run_tick(env)
            self.assertEqual(rc, 0, out)

            log_text = _metering_log_text(state_dir)
            agg_lines = [
                l for l in log_text.splitlines()
                if re.search(r'outcome backlog: \d+ job', l)
            ]
            self.assertEqual(len(agg_lines), 1, log_text)
            self.assertIn(
                ' 1 job', agg_lines[0],
                f'aggregate must count the DISTINCT job (1), not the raw '
                f'queue-entry count (2) produced by the double push:\n{agg_lines[0]}',
            )

            # Companion control: the per-job line is already correctly
            # deduplicated pre-fix -- proves the bug is isolated to the
            # aggregate counter, not the per-job WARN line.
            self.assertEqual(len(_deferred_or_wedged_lines(log_text)), 1, log_text)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Row 7: common.sh declaration shape
# ---------------------------------------------------------------------------

class CommonShOutcomeWarnDeclarationTests(unittest.TestCase):
    def test_outcome_warn_flags_dir_declared_with_override_shape(self):
        """Mirrors CommonShDeclarationTests.test_fallback_warn_flags_dir_declared_with_override_shape
        in tests/test_bounded_logging.py -- same override idiom, fourth
        member of the sentinel family."""
        text = COMMON_SH.read_text()
        self.assertRegex(
            text,
            r'OUTCOME_WARN_FLAGS_DIR="\$\{REVENIUM_OUTCOME_WARN_FLAGS_DIR:-'
            r'\$\{MARKERS_DIR\}/\.outcome-warn\}"',
        )


# ---------------------------------------------------------------------------
# Row 8: prune-markers.sh GC path
# ---------------------------------------------------------------------------

class PruneOutcomeWarnFlagsDirTests(unittest.TestCase):
    def test_prune_removes_stale_flags_keeps_fresh_in_outcome_warn_dir(self):
        """Mirrors PruneFlagDirectoriesTests.test_prune_removes_stale_flags_keeps_fresh_in_both_dirs
        in tests/test_bounded_logging.py, scoped to the new directory."""
        with tempfile.TemporaryDirectory(prefix='gsd-phase39-prune-') as tmp:
            hermes_home = os.path.join(tmp, 'hh')
            state_dir = os.path.join(hermes_home, 'state', 'revenium')
            markers_dir = os.path.join(state_dir, 'markers')
            outcome_warn_dir = os.path.join(markers_dir, '.outcome-warn')
            os.makedirs(outcome_warn_dir, mode=0o700)

            old_ts = time.time() - 31 * 86400
            new_ts = time.time()

            old_flag = os.path.join(outcome_warn_dir, 'p39job-old__deferred.flag')
            fresh_flag = os.path.join(outcome_warn_dir, 'p39job-fresh__deferred.flag')

            Path(old_flag).touch()
            os.utime(old_flag, (old_ts, old_ts))
            Path(fresh_flag).touch()
            os.utime(fresh_flag, (new_ts, new_ts))

            env = {
                **os.environ,
                'HERMES_HOME': hermes_home,
                'REVENIUM_STATE_DIR': state_dir,
                'REVENIUM_MARKERS_DIR': markers_dir,
                'REVENIUM_MARKER_RETENTION_DAYS': '30',
                'TZ': 'UTC',
            }

            # --dry-run: nothing removed.
            r = subprocess.run(
                ['bash', str(PRUNE_MARKERS), '--dry-run'],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(os.path.exists(old_flag), 'dry-run must remove nothing')
            self.assertTrue(os.path.exists(fresh_flag), 'dry-run must remove nothing')

            # Live run: only the stale flag removed.
            r = subprocess.run(
                ['bash', str(PRUNE_MARKERS)],
                env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse(
                os.path.exists(old_flag), 'stale OUTCOME_WARN_FLAGS_DIR flag must be removed',
            )
            self.assertTrue(
                os.path.exists(fresh_flag), 'fresh OUTCOME_WARN_FLAGS_DIR flag must be kept',
            )


if __name__ == '__main__':
    unittest.main()
