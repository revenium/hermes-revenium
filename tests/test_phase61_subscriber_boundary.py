"""Phase 61 Plan 02 (SUB-01/SUB-02/SUB-04): the phase-boundary differential,
plus the fail-closed / no-special-casing / masking / structural invariants
that back it up.

WHY THIS MODULE EXISTS (T-61-07): `tests/_compat_helpers.py::assert_argv_matches_golden`
(lines 104-133) iterates only `exact_match_fields`, `pattern_fields` and
`forbidden_fields` from a loaded golden JSON. It never asserts argv LENGTH or
the ordered set of flag names present. A newly added flag on either
`meter completion` emit path in hermes-report.sh would therefore pass every
one of the 11 existing golden fixtures untouched -- nothing in a golden's own
allowlist would ever notice an EXTRA flag arriving alongside the ones it
already checks for. "All 7 test_compat_* modules still report OK" is
NECESSARY but NOT SUFFICIENT proof that Phase 61 added no CLI flag. This
module supplies the sufficient complement: full-argv-length equality,
ordered-flag-name equality, and full timestamp-normalised value equality,
each asserted separately (so a failure names exactly which kind of drift
occurred), run once with NO subscriber resolved and once WITH one resolved,
on both completion emit paths (marker and markerless).

Task 1's <done> criterion required demonstrating the contrast directly: a
deliberately added flag on one emit path was appended to `hermes-report.sh`,
confirmed to make this module FAIL while `test_compat_meter_completion` (and
the other six `test_compat_*` modules) kept reporting `OK`, and then
reverted -- `git diff --quiet skills/revenium/scripts/hermes-report.sh`
exits 0 in the tree this module ships in. The experiment and its exact
output are recorded in 61-02-SUMMARY.md, not in this file -- the added flag
is never left in the tree or committed.

This module deliberately keeps the weaker golden-based assertion alongside
the exhaustive one (see GoldenCoexistenceWithResolvedSubscriberTests below):
the three timestamp fields are UNASSERTED by this module's own differential
by construction (their values are replaced by a sentinel before comparison,
so a regression that only changed a timestamp's FORMAT would slip past every
test in this file) and `assert_argv_matches_golden`'s `pattern_fields` is
what catches exactly that shape of drift. Neither assertion alone is
complete; together they are.

Reuses tests.test_phase61_identity_resolution's `_seed_sessions_db`,
`_write_marker_lines`, `_task_marker` and `_own_meter_invocations` by
import rather than copying them -- a second copy of that harness silently
drifting out of sync with what production actually does is exactly the
fixture-fidelity defect class this repo has hit five times before.

Every actor id and email address seeded in this module is synthetic and
`p61-`-prefixed (or `p61`-containing), or is `USLACKBOT` -- Slack's own
fixed, publicly-documented system bot id, already reused from
test_phase61_identity_resolution.py's `test_bot_id_resolves_identically_to_human`
-- per T-61-08: no value here is copied from any reference host.
"""
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._compat_helpers import (
    assert_argv_matches_golden,
    build_shim,
    build_state_db,
    load_golden,
    run_script,
    SCRIPTS_DIR,
)
from tests.test_phase61_identity_resolution import (
    _OLD_TS,
    _own_meter_invocations,
    _seed_sessions_db,
    _task_marker,
    _write_marker_lines,
)

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'

# The 14 columns SUB-01 pins in hermes-report.sh's main SELECT, in the exact
# order the positional `read` loop depends on. `user_id` is the literal name
# BOTH branches of `user_id_select_expr` alias to (`... AS user_id`), so the
# dynamic `${user_id_select_expr}` slot in the raw script source maps to this
# name regardless of which capability-probe branch produced it.
_EXPECTED_SELECT_COLUMNS = [
    'id', 'model', 'source', 'input_tokens', 'output_tokens',
    'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens',
    'estimated_cost_usd', 'api_call_count', 'started_at', 'ended_at',
    'billing_provider', 'user_id',
]

_TIMESTAMP_FLAGS = ('--request-time', '--completion-start-time', '--response-time')
_TS_SENTINEL = 'TIMESTAMP_SENTINEL'


# ---------------------------------------------------------------------------
# Differential helpers (Task 1)
# ---------------------------------------------------------------------------

def _normalize_timestamps(argv):
    """Return a COPY of `argv` with the VALUES of the three timestamp flags
    replaced by a constant sentinel. Flag names, their position, and every
    OTHER value are left untouched. These three fields are the only ones
    meter-completion.golden.json's own `pattern_fields` treats as
    legitimately different between two runs of the same fixture (two
    independent `date` calls), so they are the only ones this module elects
    not to compare by value."""
    out = list(argv)
    i = 0
    while i < len(out) - 1:
        if out[i] in _TIMESTAMP_FLAGS:
            out[i + 1] = _TS_SENTINEL
            i += 2
            continue
        i += 1
    return out


def _flag_names(argv):
    """Ordered list of `--flag` tokens in argv (values excluded)."""
    return [tok for tok in argv if tok.startswith('--')]


def _assert_argv_equal_modulo_timestamps(test_case, argv_a, argv_b, label):
    """The three assertions Task 1's <action> requires, kept SEPARATE so a
    failure names exactly which kind of drift occurred rather than just
    "the lists differ":
      1. argv LENGTH equal -- a flag was added or removed.
      2. ordered flag-NAME list equal -- a flag moved (or was renamed).
      3. full normalised-VALUE list equal (as ORDERED lists, not sets) --
         a value changed. Order drift is drift: `assertEqual` on lists, not
         `assertCountEqual`.
    """
    test_case.assertEqual(
        len(argv_a), len(argv_b),
        f'{label}: argv LENGTH differs -- a flag was added or removed.\n'
        f'A ({len(argv_a)} tokens): {argv_a}\nB ({len(argv_b)} tokens): {argv_b}'
    )
    test_case.assertEqual(
        _flag_names(argv_a), _flag_names(argv_b),
        f'{label}: ordered flag-NAME list differs -- a flag moved.\n'
        f'A flags: {_flag_names(argv_a)}\nB flags: {_flag_names(argv_b)}'
    )
    test_case.assertEqual(
        _normalize_timestamps(argv_a), _normalize_timestamps(argv_b),
        f'{label}: normalised full argv lists differ -- a value changed.\n'
        f'A: {_normalize_timestamps(argv_a)}\nB: {_normalize_timestamps(argv_b)}'
    )


class _Harness:
    """One temp HERMES_HOME + PATH-shim `revenium` + one meter log, mirroring
    tests.test_phase61_identity_resolution.Phase61IdentityResolutionEndToEndTestCase's
    setUp/tearDown, but packaged so a SINGLE test method can stand up
    multiple INDEPENDENT trees (one per differential arm) without
    unittest's per-test fixture lifecycle conflating them -- the whole point
    of the differential is that run A and run B are two separate processes,
    each unaware the other exists, so any shared state between them would
    itself be a source of false-negative "argv matched" results.
    """

    def __init__(self, prefix='gsd-phase61-boundary-'):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.hermes_home = os.path.join(self.tmp, 'hh')
        self.state_dir = os.path.join(self.hermes_home, 'state', 'revenium')
        self.markers_dir = os.path.join(self.state_dir, 'markers')
        os.makedirs(self.markers_dir, mode=0o700)
        self.state_db = os.path.join(self.hermes_home, 'state.db')
        self.log_file = os.path.join(self.state_dir, 'revenium-metering.log')

        self.shim_home = os.path.join(self.tmp, 'home')
        self.bin_dir = os.path.join(self.shim_home, '.local', 'bin')
        os.makedirs(self.bin_dir)
        self.meter_log = os.path.join(self.tmp, 'meter.log')
        self.jobs_log = os.path.join(self.tmp, 'jobs.log')
        self.inv_log = os.path.join(self.tmp, 'inv.log')
        self.shim = os.path.join(self.bin_dir, 'revenium')
        build_shim(self.shim, squad_capable=True)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_env(self):
        return {
            **os.environ,
            'HOME': self.shim_home,
            'HERMES_HOME': self.hermes_home,
            'REVENIUM_STATE_DIR': self.state_dir,
            'PATH': self.bin_dir + os.pathsep + os.environ.get('PATH', ''),
            'INVOCATIONS_LOG': self.inv_log,
            'METER_LOG': self.meter_log,
            'JOBS_LOG': self.jobs_log,
            'TZ': 'UTC',
            'REVENIUM_ORGANIZATION_NAME': '',
            'REVENIUM_SQUAD_NAME': '',
        }

    def run(self):
        rc, _ignored_inv, output = run_script(
            HERMES_REPORT_SH, self.base_env(), self.inv_log
        )
        meter_invocations = []
        if os.path.exists(self.meter_log):
            with open(self.meter_log) as f:
                for line in f:
                    line = line.rstrip('\n')
                    if line:
                        meter_invocations.append(shlex.split(line))
        if rc != 0:
            raise AssertionError(f'hermes-report.sh failed (rc={rc}): {output}')
        return meter_invocations

    def log_lines(self):
        if not os.path.exists(self.log_file):
            return []
        return Path(self.log_file).read_text().splitlines()


def _run_one(seed_callable, sid, with_marker, muid='p61-diff-muid'):
    """Stand up ONE temp tree, seed it via `seed_callable(state_db_path)`,
    optionally write ONE task marker for `sid`, run hermes-report.sh once,
    and return (own_invocations, log_lines) for that session. The tree is
    torn down before returning -- callers get data, not a live harness."""
    tree = _Harness()
    try:
        seed_callable(tree.state_db)
        if with_marker:
            _write_marker_lines(tree.markers_dir, sid, [_task_marker(sid, muid)])
        invocations = tree.run()
        own = _own_meter_invocations(invocations, sid)
        return own, tree.log_lines()
    finally:
        tree.cleanup()


class SubscriberBoundaryDifferentialTests(unittest.TestCase):
    """Task 1: the exhaustive argv differential. Each test seeds the IDENTICAL
    fixture shape twice, in two independent temp trees -- run A resolves NO
    subscriber, run B resolves one -- and asserts the emitted `meter
    completion` argv is equal (modulo the three timestamp field VALUES) as
    an ORDERED list, not a set.
    """

    def test_marker_path_value_differential_argv_identical(self):
        """Same 15-column schema in both runs (both HAVE the user_id column);
        only the ROW's value differs -- run A's is NULL, run B's is a real
        actor under source='slack'. This is the arm that isolates "a
        subscriber resolved from an already-present column" from any schema
        question.

        MISSES: says nothing about the schema-absent case (the capability
        probe's OTHER branch) -- that is the next test below. Also exercises
        only the marker (per-muid split) emit path, not the markerless one
        -- covered separately below.
        """
        sid = 'p61-diff-marker-value'
        own_a, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack'},
            ]),
            sid, with_marker=True,
        )
        own_b, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack', 'user_id': 'p61-actor-mv'},
            ]),
            sid, with_marker=True,
        )
        self.assertEqual(len(own_a), 1, f'run A: {own_a!r}')
        self.assertEqual(len(own_b), 1, f'run B: {own_b!r}')
        _assert_argv_equal_modulo_timestamps(
            self, own_a[0], own_b[0], 'marker path, value differential'
        )

    def test_marker_path_schema_differential_argv_identical(self):
        """Run A's `sessions` table has NO `user_id` column at all (built via
        `tests._compat_helpers.build_state_db`, the exact 13-column shape
        used at 139 call sites across 39 files); run B's has the column,
        populated. This is the arm that proves the capability probe's
        ABSENT branch changes nothing on the wire, which is what keeps all
        139 `build_state_db` call sites honest as backward-compatibility
        fixtures rather than silently-stale ones.

        MISSES: proves the two SELECT branches produce identical argv for
        THIS fixture shape; it does not enumerate every possible
        `PRAGMA table_info` result `sessions_has_user_id` could see on a
        real, differently-migrated install.
        """
        sid = 'p61-diff-marker-schema'
        own_a, _ = _run_one(
            lambda db: build_state_db(db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'slack',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
                'estimated_cost': '0', 'api_calls': 1,
                'started_at': _OLD_TS, 'ended_at': _OLD_TS,
                'billing_provider': 'anthropic',
            }]),
            sid, with_marker=True,
        )
        own_b, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack', 'user_id': 'p61-actor-ms'},
            ]),
            sid, with_marker=True,
        )
        self.assertEqual(len(own_a), 1, f'run A: {own_a!r}')
        self.assertEqual(len(own_b), 1, f'run B: {own_b!r}')
        _assert_argv_equal_modulo_timestamps(
            self, own_a[0], own_b[0], 'marker path, schema differential'
        )

    def test_markerless_path_value_differential_argv_identical(self):
        """The value differential again, but for a session with NO marker
        file -- the markerless emit path (`--transaction-id
        "${sid}-${total_tokens}"`, no muid suffix), which is a physically
        different `cmd=(...)` array in hermes-report.sh from the per-marker
        one above and must be proven separately.

        MISSES: says nothing about the marker path (covered above) or the
        schema-absent case on THIS path (covered next).
        """
        sid = 'p61-diff-markerless-value'
        own_a, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack'},
            ]),
            sid, with_marker=False,
        )
        own_b, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack', 'user_id': 'p61-actor-mlv'},
            ]),
            sid, with_marker=False,
        )
        self.assertEqual(len(own_a), 1, f'run A: {own_a!r}')
        self.assertEqual(len(own_b), 1, f'run B: {own_b!r}')
        _assert_argv_equal_modulo_timestamps(
            self, own_a[0], own_b[0], 'markerless path, value differential'
        )

    def test_markerless_path_schema_differential_argv_identical(self):
        """The schema differential again, on the markerless path.

        MISSES: same as the marker-path schema differential above -- proves
        this fixture shape only, not every real install's schema history.
        Together with the three tests above, this is the FULL 2x2 (marker
        vs markerless) x (value vs schema) matrix the plan's <behavior>
        specifies.
        """
        sid = 'p61-diff-markerless-schema'
        own_a, _ = _run_one(
            lambda db: build_state_db(db, [{
                'id': sid, 'model': 'claude-sonnet-4-6', 'source': 'slack',
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read': 0, 'cache_write': 0, 'reasoning': 0,
                'estimated_cost': '0', 'api_calls': 1,
                'started_at': _OLD_TS, 'ended_at': _OLD_TS,
                'billing_provider': 'anthropic',
            }]),
            sid, with_marker=False,
        )
        own_b, _ = _run_one(
            lambda db: _seed_sessions_db(db, [
                {'id': sid, 'source': 'slack', 'user_id': 'p61-actor-mls'},
            ]),
            sid, with_marker=False,
        )
        self.assertEqual(len(own_a), 1, f'run A: {own_a!r}')
        self.assertEqual(len(own_b), 1, f'run B: {own_b!r}')
        _assert_argv_equal_modulo_timestamps(
            self, own_a[0], own_b[0], 'markerless path, schema differential'
        )


class GoldenCoexistenceWithResolvedSubscriberTests(unittest.TestCase):
    """Task 1, "Golden coexistence": reproduce
    test_compat_meter_completion.py's EXACT fixture (same sid, muid, job id,
    model, tokens, environment) but ADD a resolved subscriber (a populated
    `user_id` column via the module-local 15-column schema instead of
    `build_state_db`'s 13-column one), and assert the resulting argv still
    satisfies `assert_argv_matches_golden` against the real
    `meter-completion.golden.json` fixture wholesale -- every
    `exact_match_fields`/`pattern_fields`/`forbidden_fields` entry the golden
    declares is reproduced by this fixture, so this is a FULL pass, not a
    partial one restricted to a hand-picked subset.

    WHY THIS ASSERTION IS KEPT even though it is the WEAKER one (per the
    module docstring's finding): its `pattern_fields` regexes are the only
    check in this whole module that inspects the FORMAT of the three
    timestamp fields (this module's own differential replaces their values
    with a sentinel and never looks at them again). A regression that
    changed only a timestamp's format -- ISO-8601 to epoch seconds, say --
    would pass every test above and be caught only here.

    MISSES: `assert_argv_matches_golden` still does not assert argv length
    or the full flag-name set -- that gap is exactly why
    SubscriberBoundaryDifferentialTests exists above. This test proves
    coexistence, not sufficiency, on its own.
    """

    def test_resolved_subscriber_argv_still_matches_golden_wholesale(self):
        tree = _Harness(prefix='gsd-phase61-golden-coexist-')
        try:
            _seed_sessions_db(tree.state_db, [{
                'id': 'compat-sid-001',
                'model': 'claude-sonnet-4-6',
                'source': 'test',
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_read': 0,
                'cache_write': 0,
                'reasoning': 0,
                'estimated_cost': 0.0,
                'api_calls': 1,
                'started_at': 1715514000.0,
                'ended_at': 1715514000.0,
                'billing_provider': 'anthropic',
                'user_id': 'p61-golden-actor',
            }])
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
            _write_marker_lines(
                tree.markers_dir, 'compat-sid-001', [task_marker, job_marker]
            )
            invocations = tree.run()
            self.assertEqual(len(invocations), 1, invocations)
            captured = invocations[0]
            self.assertEqual(captured[0], 'meter')
            self.assertEqual(captured[1], 'completion')
            assert_argv_matches_golden(
                self, captured, load_golden('meter-completion.golden.json')
            )
        finally:
            tree.cleanup()


if __name__ == '__main__':
    unittest.main()
