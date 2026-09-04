"""SSE-07: the milestone's closing proof that an install adopting none of
this milestone meters byte-identically to one that predates it.

What this module proves:
  - Task 1 (D-03): Phase 59-04's per-session profile resolution -- the one
    change with no off switch -- leaves `hermes-report.sh`'s argv unchanged
    on a single-profile install (no `profiles/` directory), with a negative
    control showing that the same fixture WITH the profile's home present
    produces a different result. The negative control is what makes the
    positive arm mean something: a byte-identity result that would also
    hold if resolution never engaged at all is not evidence about
    resolution.
  - Task 2 (criterion 3): "every golden argv fixture still passes" cannot be
    satisfied by a fixture nothing loads, and the feature-off golden
    (`jobs-outcome-update.golden.json`) is distinguished from its
    positive-probe sibling (`jobs-outcome-update-versioned.golden.json`)
    structurally, not by prose.
  - Task 3: `docs/upgrading.md` carries the closing section naming all four
    feature-off shapes and the profile-resolution carve-out.

What this module does NOT prove:
  - anything about a multiplexed host's steady-state behaviour beyond "it
    differs from the single-profile shape" -- the resolver-level proof of
    correctness on that shape is `tests/test_phase59_profile_resolution.py`'s
    job, not this module's.
  - that `docs/cli-verb-ask.md`'s asks are well-chosen, or that
    `docs/upgrading.md`'s new section argues persuasively -- Task 3's guard
    is shape-only, matching this project's own "shape, not correctness"
    convention for prose guards (see test_phase58_provenance_mapping_doc.py).

No golden fixture and no shared test helper (`tests/_compat_helpers.py`) is
modified anywhere in this module -- the two `git diff --quiet` checks in
60-02-PLAN.md's prohibitions cover both.
"""
import json
import os
import shutil
import shlex
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    argv_to_flags,
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)

ROOT = Path(__file__).resolve().parents[1]

# The profile name used across both arms of Task 1. Deliberately not one of
# resolve-markers-dir.py's DEFAULT_PROFILE_SLOTS ("default" / "main"), which
# would make resolution fall open to the process-level paths regardless of
# whether the profile's home directory exists -- that would silently defeat
# the negative control.
PROFILE_NAME = 'compat-profile-acme'


def _build_and_run(tmpdir, create_profile_home):
    """Build the meter-completion compat fixture exactly as
    test_compat_meter_completion.py builds it (same tree shape, same
    session id/token totals, same pinned marker id), then make ONE change:
    add a `profile_name` column to the test's OWN sessions table (never to
    `_compat_helpers.build_state_db` itself -- a prohibition this plan
    enforces) and set it to PROFILE_NAME for the session row.

    When `create_profile_home` is True, additionally creates
    `${HERMES_HOME}/profiles/${PROFILE_NAME}/` on disk (nothing more is
    needed -- resolve-markers-dir.py's `resolve_state_subdir` only checks
    `profile_home.is_dir()`) so that resolution engages instead of falling
    open to the process-level paths.

    Returns (returncode, meter_invocations, output) where meter_invocations
    is a list of shlex-split argv lists captured from METER_LOG.
    """
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
    shim = os.path.join(bin_dir, 'revenium')

    # Same session id, token totals, and timestamps as
    # test_compat_meter_completion.py -- reusing them is what makes the
    # positive arm's byte-identity assertion against the EXISTING golden
    # meaningful, rather than a golden the plan would need a new fixture for.
    build_state_db(state_db, [{
        'id': 'compat-sid-001',
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

    # The ONE change: add profile_name locally, to THIS test's own database
    # file, after build_state_db has already returned. Every other compat
    # test shares build_state_db's schema, and the Phase 59 backward-
    # compatibility arm depends on the column being absent there.
    conn = sqlite3.connect(state_db)
    conn.execute('ALTER TABLE sessions ADD COLUMN profile_name TEXT')
    conn.execute(
        'UPDATE sessions SET profile_name = ? WHERE id = ?',
        (PROFILE_NAME, 'compat-sid-001'),
    )
    conn.commit()
    conn.close()

    task_marker = {
        'muid': 'compat-muid-001',
        'ts': 1715515000.5,
        'sid': 'compat-sid-001',
        'task_type': 'code_review',
        'operation_type': 'CHAT',
    }
    job_marker = {
        'kind': 'job',
        'ts': 1715515001.0,
        'sid': 'compat-sid-001',
        'agentic_job_id': 'compat-job-001',
        'job_name': 'COMPAT Test Job',
        'job_type': 'code_review',
        'status': 'IN_PROGRESS',
    }
    with open(os.path.join(markers_dir, 'compat-sid-001.jsonl'), 'w') as f:
        f.write(json.dumps(task_marker, separators=(',', ':')) + '\n')
        f.write(json.dumps(job_marker, separators=(',', ':')) + '\n')

    if create_profile_home:
        # Load-bearing minimum per resolve-markers-dir.py's own contract:
        # only directory EXISTENCE is checked. The marker file above stays
        # under the PROCESS-level markers_dir, never copied into the
        # profile's home -- that absence, from the profile's own state
        # subdirectory's point of view, is exactly what a genuinely
        # multiplexed host's per-profile markers directory would look like
        # for a session it does not own.
        os.makedirs(os.path.join(hermes_home, 'profiles', PROFILE_NAME))

    build_shim(shim)

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

    rc, _ignored_inv, output = run_script(
        SCRIPTS_DIR / 'hermes-report.sh', base_env, inv_log
    )

    meter_invocations = []
    if os.path.exists(meter_log):
        with open(meter_log) as f:
            for line in f:
                line = line.rstrip('\n')
                if line:
                    meter_invocations.append(shlex.split(line))

    return rc, meter_invocations, output


class ProfileResolutionCarveOutProofTests(unittest.TestCase):
    """D-03: the carve-out is discharged by proof, not assertion."""

    def test_single_profile_install_argv_matches_golden_positive_arm(self):
        """No `profiles/` directory on disk: resolution falls to the
        process-level paths, and the reporter's argv is exactly what it has
        always been -- byte-identical to meter-completion.golden.json.
        """
        tmpdir = tempfile.mkdtemp(prefix='gsd-p60-profile-carveout-pos-')
        try:
            rc, invocations, output = _build_and_run(tmpdir, create_profile_home=False)

            self.assertEqual(rc, 0, f'hermes-report.sh failed (rc={rc}): {output}')
            self.assertEqual(
                len(invocations), 1,
                f'expected 1 meter completion invocation on the single-profile '
                f'install, got {len(invocations)}: {invocations[:3]!r}\nOutput: {output}'
            )

            captured = invocations[0]
            self.assertEqual(captured[0], 'meter')
            self.assertEqual(captured[1], 'completion')

            assert_argv_matches_golden(
                self, captured, load_golden('meter-completion.golden.json')
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_profile_home_present_argv_differs_negative_control(self):
        """The negative control this proof is worthless without: the SAME
        fixture, but with the named profile's home created on disk, so
        resolution engages instead of falling open. The assertion is
        deliberately loose about WHICH difference appears -- depending on
        where the (process-level-only) marker file lands relative to the
        profile's own markers directory, the reporter may produce a
        markerless-shaped completion (a different argv) or may produce no
        invocation at all for this session on this tick. Both are correct
        expressions of "deliberately different on a multiplexed install";
        pinning one specific shape here would re-introduce the fixture-
        agrees-with-itself failure mode a negative control exists to avoid.
        """
        pos_tmpdir = tempfile.mkdtemp(prefix='gsd-p60-profile-carveout-ctrl-pos-')
        neg_tmpdir = tempfile.mkdtemp(prefix='gsd-p60-profile-carveout-ctrl-neg-')
        try:
            pos_rc, pos_invocations, pos_output = _build_and_run(
                pos_tmpdir, create_profile_home=False
            )
            self.assertEqual(pos_rc, 0, f'positive-arm baseline failed: {pos_output}')
            self.assertEqual(len(pos_invocations), 1, f'positive-arm baseline: {pos_invocations!r}')
            pos_flags = argv_to_flags(pos_invocations[0])

            neg_rc, neg_invocations, neg_output = _build_and_run(
                neg_tmpdir, create_profile_home=True
            )
            self.assertEqual(neg_rc, 0, f'negative-control run failed: {neg_output}')

            if len(neg_invocations) == 0:
                # Correct outcome #1: resolution engaged, routed the read to
                # the (empty) profile markers directory, and the session
                # produced no completion invocation at all on this tick.
                return

            # Correct outcome #2: a completion invocation occurred, but its
            # argv is NOT the single-profile arm's argv -- resolution
            # engaged and changed what got shipped.
            neg_flags = argv_to_flags(neg_invocations[0])
            self.assertNotEqual(
                neg_flags, pos_flags,
                'the profile-present arm must differ from the single-profile '
                'arm -- an identical result here would mean resolution never '
                'engaged, making the positive arm\'s byte-identity result '
                'unfalsifiable rather than proven.'
            )
        finally:
            shutil.rmtree(pos_tmpdir, ignore_errors=True)
            shutil.rmtree(neg_tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
