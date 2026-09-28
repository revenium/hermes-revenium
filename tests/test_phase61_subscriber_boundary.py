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

PHASE 62 (SUB-05/07/08, D-13) UPDATE:

Phase 61's own charter for this module was "no wire change happens in this
phase" -- every differential above asserted `argv_a == argv_b` (run A no
subscriber, run B one) as PROOF of that absence. Phase 62's entire purpose is
to cross that boundary: `--subscriber-id` now ships. All four
`SubscriberBoundaryDifferentialTests` methods are INVERTED, not deleted, into
`_assert_argv_equal_modulo_timestamps_plus_tail`: each now asserts run B
equals run A plus exactly the two subscriber tokens. This is what closing
Phase 61 review item IN-01 actually looks like -- the differential remains
the strongest argv-shape assertion in the suite, now proving the PRESENT arm
instead of the absent one. `GoldenCoexistenceWithResolvedSubscriberTests` and
`StructuralInvariantTests` are unaffected and stay as written.

`test_boundary_files_unmodified_relative_to_merge_base` (formerly in
`StructuralInvariantTests`) is RETIRED, not just edited. It asserted a
Phase-61-specific claim -- that `tests/fixtures/compat/`, `tests/_compat_helpers.py`
and `skills/revenium/scripts/api-event-report.sh` were UNMODIFIED relative to
the merge base with `main` -- and Phase 62's entire purpose is to touch the
first two of those three deliberately (this plan edits both; Plan 62-02 edits
the third). A guard whose premise a later phase is chartered to violate must
be removed with a record, not left to fail forever or silently patched to
tolerate the exact drift it existed to catch. Its replacement proof is this
phase's own per-site `argv_order` equality (`assert_argv_is_golden_argv_order`
in `tests/_compat_helpers.py`, consumed by `tests/test_phase62_subscriber_wiring.py`):
where the retired test asserted "these files never changed", the replacement
asserts the STRONGER claim that emitted argv changed in EXACTLY the way this
phase intends (golden argv_order plus exactly two trailing tokens when an
actor resolves, byte-identical to it otherwise) -- a property the merge-base
diff could never express. Separately, the retired test's own docstring
recorded that it SKIPPED (never failed) whenever the repository could not
resolve a merge-base against `main` -- true on every shallow CI checkout
without `fetch-depth: 0` -- so its removal loses less real coverage than its
name suggests: a green CI run was never proof it had executed.
"""
import os
import re
import shlex
import shutil
import subprocess
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
from tests.test_phase61_identity_resolution import (
    COMMON_SH,
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


def _assert_argv_equal_modulo_timestamps_plus_tail(
    test_case, argv_a, argv_b, extra_tail, label
):
    """Phase 62 (SUB-05/D-13): inverted sibling of
    `_assert_argv_equal_modulo_timestamps` above. Run A resolves NO
    subscriber; run B resolves one. Since Phase 62 wires `--subscriber-id`,
    "identical" is no longer the correct claim -- "identical plus exactly
    these `extra_tail` tokens" is. Same three SEPARATE assertions as the
    un-inverted sibling (length, ordered flag-name list, normalised full
    value list), so a failure still names exactly which kind of drift
    occurred; only the expected shape of B changes.
    """
    expected_b = list(argv_a) + list(extra_tail)
    test_case.assertEqual(
        len(expected_b), len(argv_b),
        f'{label}: argv LENGTH differs from A + extra_tail={list(extra_tail)} '
        f'-- a flag was added or removed.\n'
        f'A+tail ({len(expected_b)} tokens): {expected_b}\nB ({len(argv_b)} tokens): {argv_b}'
    )
    test_case.assertEqual(
        _flag_names(expected_b), _flag_names(argv_b),
        f'{label}: ordered flag-NAME list differs from A + extra_tail -- a '
        f'flag moved.\nA+tail flags: {_flag_names(expected_b)}\nB flags: {_flag_names(argv_b)}'
    )
    test_case.assertEqual(
        _normalize_timestamps(expected_b), _normalize_timestamps(argv_b),
        f'{label}: normalised full argv lists differ from A + extra_tail -- a '
        f'value changed.\nA+tail: {_normalize_timestamps(expected_b)}\n'
        f'B: {_normalize_timestamps(argv_b)}'
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
        # subscriber_capable=True (Phase 62): the differentials below need
        # SUBSCRIBER_CLI_CAPABLE to resolve true so a resolved actor actually
        # reaches the wire -- an incapable shim would make every "present"
        # arm look identical to "absent" by construction, hiding the exact
        # regression this harness exists to catch.
        build_shim(self.shim, squad_capable=True, subscriber_capable=True)

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
        """PHASE 62 (SUB-05/D-13) INVERTED: this test's ORIGINAL claim (Phase
        61) was that runs A and B produce IDENTICAL argv, because Phase 61
        added no wire flag. Phase 62 wires `--subscriber-id` at the
        marker-split site too, so a session that resolves an actor now MUST
        differ from one that does not -- by exactly the two subscriber
        tokens.

        Same 15-column schema in both runs (both HAVE the user_id column);
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
        _assert_argv_equal_modulo_timestamps_plus_tail(
            self, own_a[0], own_b[0],
            ('--subscriber-id', 'slack:p61-actor-mv'),
            'marker path, value differential',
        )

    def test_marker_path_schema_differential_argv_identical(self):
        """PHASE 62 (SUB-05/D-13) INVERTED, same rationale as the value
        differential above.

        Run A's `sessions` table has NO `user_id` column at all (built via
        `tests._compat_helpers.build_state_db`, the exact 13-column shape
        used at 139 call sites across 39 files); run B's has the column,
        populated. This is the arm that proves the capability probe's
        ABSENT branch changes NOTHING on the wire, which is what keeps all
        139 `build_state_db` call sites honest as backward-compatibility
        fixtures rather than silently-stale ones, now that a real flag
        exists to leak.

        MISSES: proves the two SELECT branches produce argv differing by
        exactly the subscriber tail for THIS fixture shape; it does not
        enumerate every possible `PRAGMA table_info` result
        `sessions_has_user_id` could see on a real, differently-migrated
        install.
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
        _assert_argv_equal_modulo_timestamps_plus_tail(
            self, own_a[0], own_b[0],
            ('--subscriber-id', 'slack:p61-actor-ms'),
            'marker path, schema differential',
        )

    def test_markerless_path_value_differential_argv_identical(self):
        """PHASE 62 (SUB-05/D-13) INVERTED: this test's ORIGINAL claim (Phase
        61) was that runs A and B produce IDENTICAL argv, because Phase 61
        added no wire flag. Phase 62 wires `--subscriber-id`, so a session
        that resolves an actor now MUST differ from one that does not -- by
        exactly the two subscriber tokens, in exactly this position. The
        differential is inverted, not deleted: it remains the strongest
        argv-shape assertion in the suite, now proving the PRESENT arm
        (Phase 61 review item IN-01's recommendation, landed at the moment
        it becomes the right tool) rather than the absent one.

        Same 15-column schema in both runs (both HAVE the user_id column);
        only the ROW's value differs -- run A's is NULL, run B's is a real
        actor under source='slack'. This is the arm that isolates "a
        subscriber resolved from an already-present column" from any schema
        question, for the markerless emit path (`--transaction-id
        "${sid}-${total_tokens}"`, no muid suffix), which is a physically
        different `cmd=(...)` array in hermes-report.sh from the per-marker
        one and must be proven separately.

        MISSES: says nothing about the marker path (covered in Plan 62-01
        Task 2) or the schema-absent case on THIS path (covered next).
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
        _assert_argv_equal_modulo_timestamps_plus_tail(
            self, own_a[0], own_b[0],
            ('--subscriber-id', 'slack:p61-actor-mlv'),
            'markerless path, value differential',
        )

    def test_markerless_path_schema_differential_argv_identical(self):
        """PHASE 62 (SUB-05/D-13) INVERTED, same rationale as the value
        differential above. This arm is the one that proves the capability
        probe's ABSENT branch (run A, built via `build_state_db`, the exact
        13-column shape used at 139 call sites across 39 files -- no
        `user_id` column at all) still changes NOTHING on the wire, which is
        what keeps every one of those 139 call sites honest as
        backward-compatibility fixtures rather than silently-stale ones, now
        that a real flag exists to leak.

        MISSES: same as the marker-path schema differential -- proves this
        fixture shape only, not every real install's schema history.
        Together with Plan 62-01 Task 2's marker-path pair, this is the FULL
        2x2 (marker vs markerless) x (value vs schema) matrix.
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
        _assert_argv_equal_modulo_timestamps_plus_tail(
            self, own_a[0], own_b[0],
            ('--subscriber-id', 'slack:p61-actor-mls'),
            'markerless path, schema differential',
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


# ---------------------------------------------------------------------------
# Task 2: resolution / fail-closed / masking / structural invariants
# ---------------------------------------------------------------------------

class ResolutionFailClosedAndMaskingTests(unittest.TestCase):
    """Unit-level contract of `resolve_subscriber_id` / `mask_subscriber_for_log`
    via the `bash -c 'source common.sh; ...'` idiom (mirroring
    tests/test_phase42_assessment_contract.py:1435-1470 and this repo's own
    tests/test_phase61_identity_resolution.py::ResolveSubscriberIdUnitTests).
    Every assertion is on the FULL `<status>|<key>` line, never on the key
    alone -- a test that only checked the key could not tell `none` from
    `rejected`, and that distinction is the entire point of D-03's sentinel.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gsd-phase61-boundary-unit-')
        self.hermes_home = os.path.join(self.tmp, 'hh')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call_common(self, fn, *args):
        quoted = ' '.join(shlex.quote(a) for a in args)
        expr = f'{fn} {quoted}'
        env = {**os.environ, 'HERMES_HOME': self.hermes_home}
        return subprocess.run(
            ['bash', '-c', f'source "{COMMON_SH}" >/dev/null 2>&1; {expr}'],
            env=env, capture_output=True, text=True, timeout=30,
        )

    # -- No special casing (SUB-04, D-06, D-12) --

    def test_bot_and_human_actor_ids_resolve_by_the_identical_rule(self):
        """D-12: a bot/app-shaped actor id (Slack's own fixed `USLACKBOT`
        system id) and a human-shaped one, under the SAME source, produce
        keys built by the identical `<source>:<actor>` rule -- assert the
        exact expected key for each.

        MISSES: proves the OUTPUT is shape-agnostic for these two concrete
        inputs; does not itself prove the FUNCTION BODY contains no shape
        conditional (a conditional that happened to produce the same output
        for exactly these two probes would pass here) -- that is the
        separate structural test below, which is why both exist.
        """
        r_bot = self._call_common('resolve_subscriber_id', 'slack', 'USLACKBOT')
        r_human = self._call_common('resolve_subscriber_id', 'slack', 'U02C12JG78F')
        self.assertEqual(r_bot.returncode, 0, r_bot.stderr)
        self.assertEqual(r_human.returncode, 0, r_human.stderr)
        self.assertEqual(r_bot.stdout.strip(), 'ok|slack:USLACKBOT')
        self.assertEqual(r_human.stdout.strip(), 'ok|slack:U02C12JG78F')

    def test_resolve_subscriber_id_body_has_no_shape_conditional(self):
        """WEAK STRUCTURAL GUARD (documented deliberately, per <action>):
        read common.sh as text, slice out `resolve_subscriber_id`'s body
        between its own `resolve_subscriber_id() {` line and its matching
        closing `}`, DROP every comment line first (the function's own
        comments legitimately NAME the shapes it deliberately does not
        branch on -- "no branch anywhere on whether the actor looks like a
        bot, an app or a person" -- so counting comments would report a
        violation that is actually the opposite of one), and assert the
        remaining CODE contains no case-insensitive occurrence of a
        bot/app-shaped literal.

        MISSES: this catches an added special case written the OBVIOUS way
        (a literal `bot`/`app` substring in a conditional). It would MISS a
        clever one -- e.g. a regex keyed on Slack's own `U0` vs `U9` id
        prefixing convention, or a length check, neither of which contains
        the word "bot" or "app" anywhere. The BEHAVIOURAL row directly
        above (bot and human resolving identically) is what carries the
        real weight; this structural grep is a cheap second line of
        defense, not a proof.
        """
        text = COMMON_SH.read_text()
        lines = text.splitlines()
        start = end = None
        for i, line in enumerate(lines):
            if line.strip() == 'resolve_subscriber_id() {':
                start = i
            elif start is not None and line.strip() == '}':
                end = i
                break
        self.assertIsNotNone(start, "resolve_subscriber_id() { not found in common.sh")
        self.assertIsNotNone(end, "matching closing '}' not found")
        body_lines = lines[start:end + 1]
        code_only = '\n'.join(
            l for l in body_lines if not l.strip().startswith('#')
        )
        for shape_kw in ('bot', 'app', 'BOT', 'APP', 'Bot', 'App'):
            self.assertNotIn(
                shape_kw, code_only,
                f"resolve_subscriber_id's CODE (comments stripped) contains "
                f"{shape_kw!r} -- a shape-based special case may have been added"
            )

    def test_unseen_source_namespaces_verbatim_no_allowlist(self):
        """D-06: a source string this skill has never seen produces a key
        namespaced under that source VERBATIM -- no allowlist gate exists
        to reject or rewrite it.

        MISSES: proves the ABSENCE of an allowlist for this one probe value;
        it cannot prove no allowlist exists for some other value never
        tried here (an allowlist keyed on a specific denylist of NAMED
        sources rather than an explicit allow-set would not be caught by a
        single novel-source probe alone -- though D-06's own measurement,
        recorded in 61-CONTEXT.md, is the authority that no such gate is
        intended anywhere in this function).
        """
        r = self._call_common(
            'resolve_subscriber_id', 'p61-future-source-never-configured', 'U1'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.strip(), 'ok|p61-future-source-never-configured:U1'
        )

    def test_automation_sources_with_empty_actor_id_produce_no_key(self):
        """D-07's NULL/empty gate is the WHOLE mechanism excluding `cli`,
        `cron`, `tui` and `subagent` -- the four sources measured at 0
        identity-bearing rows out of 9,355 on the reference host. There
        must be no SOURCE allowlist doing this instead -- each of these four
        must resolve to `none|` purely because the actor id is empty, the
        identical path any OTHER source with an empty actor id takes.

        MISSES: proves these four sources take the shared empty-gate path
        for AN empty actor id; does not prove no source-keyed special case
        exists for a NON-empty actor id under these same four sources (no
        such case is expected -- D-07 measured 0 populated rows for all
        four -- but this test's scope is the empty-actor-id row only).
        """
        for src in ('cli', 'cron', 'tui', 'subagent'):
            r = self._call_common('resolve_subscriber_id', src, '')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), 'none|', f'source={src!r}')

    # -- Fail closed (D-03's one-way hazard) --

    def test_pipe_tab_cr_lf_and_sentinel_actor_ids_all_rejected(self):
        """D-03: a transport-unsafe or un-namespaceable actor id resolves to
        `rejected|` -- never to a truncated or guessed key, and never
        silently to `none|` (which would wrongly imply "no identity" rather
        than "identity present but unsafe"). Covers a pipe, a literal tab, a
        literal CR, a literal LF, and the fixed unsafe sentinel.

        MISSES: this is the function's OWN unit contract in isolation for
        these five probe values; the end-to-end pipe test below is what
        proves a rejected value never reaches the wire or corrupts a
        neighbouring field when it originates from a REAL seeded row rather
        than a direct function call.
        """
        cases = {
            'pipe': 'U|600',
            'tab': 'U\t600',
            'cr': 'U\r600',
            'lf': 'U\n600',
            'sentinel': '__revenium_unsafe_user_id__',
        }
        for label, actor in cases.items():
            r = self._call_common('resolve_subscriber_id', 'slack', actor)
            self.assertEqual(r.returncode, 0, f'case={label!r}: {r.stderr}')
            self.assertEqual(
                r.stdout.strip(), 'rejected|',
                f'case={label!r} actor={actor!r} stdout={r.stdout!r}'
            )

    def test_nonempty_actor_id_with_empty_source_rejected_not_colon_prefixed(self):
        """A non-empty actor id with an EMPTY source resolves to `rejected|`,
        not to a colon-prefixed key like `:U1` -- an empty namespace would
        violate D-05's collision guarantee (two different empty-namespace
        sources would collide on the SAME key) just as surely as a missing
        namespace would.

        MISSES: only the fully-empty-string source case; a WHITESPACE-ONLY
        source is not separately probed here (resolve_subscriber_id trims
        both arguments before the emptiness check, so it collapses to the
        same code path, but this test does not independently re-derive
        that).
        """
        r = self._call_common('resolve_subscriber_id', '', 'U1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'rejected|')

    def test_pipe_actor_id_end_to_end_neighbouring_fields_intact(self):
        """End to end (stronger than the unit-level version above): a
        SEEDED session whose `user_id` contains a pipe is sanitised by the
        SQL delimiter-safety CASE before it ever reaches the positional
        `read`, so it is REJECTED (no key), and -- the row was not
        shifted -- its neighbouring fields (`billing_provider`,
        `input_tokens`, `output_tokens`, `total_tokens`) are read and
        forwarded CORRECTLY, verified by asserting their ACTUAL VALUES in
        the emitted argv, not merely that the run completed without error.

        MISSES: this fixture's pipe sits inside `user_id` only; it does not
        independently probe a pipe inside `source` (the "empty source"
        arm above and the unit-level `case "${source}"` guard in
        resolve_subscriber_id cover the source side of D-03, but not
        combined with a real seeded row).
        """
        sid = 'p61-pipe-e2e'
        tree = _Harness(prefix='gsd-phase61-boundary-pipe-')
        try:
            _seed_sessions_db(tree.state_db, [{
                'id': sid, 'source': 'slack', 'user_id': 'U|600',
                'billing_provider': 'anthropic',
                'input_tokens': 100, 'output_tokens': 50,
            }])
            invocations = tree.run()
            own = _own_meter_invocations(invocations, sid)
            self.assertEqual(len(own), 1, f'{own!r}')
            flags = argv_to_flags(own[0])
            self.assertEqual(flags.get('--model-source'), 'anthropic')
            self.assertEqual(flags.get('--input-tokens'), '100')
            self.assertEqual(flags.get('--output-tokens'), '50')
            self.assertEqual(flags.get('--total-tokens'), '150')

            reported = [
                l for l in tree.log_lines() if f'Reported: session={sid} ' in l
            ]
            self.assertEqual(len(reported), 1, reported)
            self.assertNotIn('subscriber=', reported[0])
        finally:
            tree.cleanup()

    # -- Masking (T-61-01) --

    def test_mask_and_resolve_differ_for_an_email(self):
        """`mask_subscriber_for_log` masks an email local part; the RESOLVED
        value `resolve_subscriber_id` itself produces for the identical
        input is EXACT and unmasked -- the two must differ, or the log-side
        mitigation has leaked into the value a future phase needs exact.

        MISSES: proves the two functions differ for ONE email-shaped input;
        does not itself prove masking is applied consistently at every
        emission site that logs a subscriber key (the end-to-end test below
        covers the one site this phase adds: the `Reported:` line).
        """
        r_resolved = self._call_common(
            'resolve_subscriber_id', 'email', 'p61user@example.test'
        )
        self.assertEqual(r_resolved.returncode, 0, r_resolved.stderr)
        self.assertEqual(
            r_resolved.stdout.strip(), 'ok|email:p61user@example.test'
        )
        resolved_key = r_resolved.stdout.strip().split('|', 1)[1]

        r_masked = self._call_common(
            'mask_subscriber_for_log', 'email:p61user@example.test'
        )
        self.assertEqual(r_masked.returncode, 0, r_masked.stderr)
        masked_value = r_masked.stdout.strip()
        self.assertEqual(masked_value, 'email:p***@example.test')
        self.assertNotEqual(
            resolved_key, masked_value,
            'resolve_subscriber_id and mask_subscriber_for_log must NOT agree '
            'for an email -- if they do, masking has leaked into the resolved '
            'value Phase 63 needs exact'
        )

    def test_email_masked_in_log_unmasked_local_part_absent(self):
        """End to end: after a run seeding an email-source session, the
        cron LOG FILE contains the masked form and does NOT contain the
        unmasked local part ANYWHERE -- grepping the log file the way an
        operator pasting it into a support ticket would see it, not the
        source tree.

        MISSES: greps ONE run's log for ONE email-shaped input; it does not
        prove masking for a source this fixture never seeds reaching this
        same emit path (structurally, every `Reported:` line funnels
        through the SAME `mask_subscriber_for_log` call per
        `subscriber_log_suffix`'s single construction site, so a second
        email fixture would not exercise new code -- but this test alone
        does not demonstrate that).
        """
        sid = 'p61-mask-e2e'
        tree = _Harness(prefix='gsd-phase61-boundary-mask-')
        try:
            _seed_sessions_db(tree.state_db, [{
                'id': sid, 'source': 'email', 'user_id': 'p61user@example.test',
            }])
            tree.run()
            log_text = '\n'.join(tree.log_lines())
            self.assertIn('subscriber=email:p***@example.test', log_text)
            self.assertNotIn('p61user@', log_text)
        finally:
            tree.cleanup()


class StructuralInvariantTests(unittest.TestCase):
    """Task 2's positive, exhaustive structural gates. Per <action>: the
    column-list assertion is a POSITIVE ordered equality against the
    fourteen expected names, chosen deliberately over a NEGATIVE grep for
    the two excluded columns (`display_name`, `origin_json`) -- a positive
    list also pins ORDER, which is what the positional `read` contract
    depends on (`api-event-report.sh`'s own "constant width... widen in
    lockstep" comment is the established statement of that rule). Every
    count-based gate here strips comment lines FIRST, per T-61-09 -- an
    UNGATED count would find its own documentation and report a violation
    that is actually the opposite of one.
    """

    def test_main_select_column_list_is_exact_ordered_and_positive(self):
        """The main session query's column list is EXACTLY the fourteen
        expected names, in order -- not a superset, not a subset, not
        merely "does not contain the two excluded columns".

        MISSES: reads the SELECT as SOURCE TEXT (a static analysis), not by
        actually running the query against a live schema -- the end-to-end
        differential tests above are what prove the QUERY, run for real,
        produces argv that does not change shape.
        """
        text = HERMES_REPORT_SH.read_text()
        matches = re.findall(
            r'SELECT id, model, source,.*?FROM sessions', text, re.DOTALL
        )
        self.assertEqual(
            len(matches), 1,
            f'expected exactly one "SELECT id, model, source, ... FROM sessions" '
            f'block in hermes-report.sh; found {len(matches)}'
        )
        body = matches[0][len('SELECT'):-len('FROM sessions')]
        columns = []
        for raw in body.split(','):
            token = ' '.join(raw.split())
            if token == '${user_id_select_expr}':
                # Both capability-probe branches of this local variable end
                # in the literal `AS user_id` alias (verified by direct read
                # of common.sh's sessions_has_user_id-gated assignment in
                # hermes-report.sh's main()) -- so the STATIC source text's
                # dynamic slot maps to this name regardless of which branch
                # runs at execution time.
                columns.append('user_id')
            elif re.search(r'\s+AS\s+', token, flags=re.IGNORECASE):
                columns.append(re.split(r'\s+AS\s+', token, flags=re.IGNORECASE)[-1])
            else:
                columns.append(token)
        self.assertEqual(columns, _EXPECTED_SELECT_COLUMNS)

    def test_read_loop_binds_fourteen_variables_positionally(self):
        """The read loop consuming the main SELECT's output binds EXACTLY
        fourteen variables, and the fourteenth (last) is `user_id` -- the
        position the fourteenth SELECT column also occupies. Position, not
        spelling, is what the positional `read -r` contract depends on, so
        this pins COUNT and the terminal position rather than requiring
        every read-side name to match its select-side counterpart's
        spelling (`cache_read` vs `cache_read_tokens`, e.g., is expected and
        harmless).

        MISSES: does not independently prove EVERY read-side variable name
        maps to the semantically-correct select-side column in the middle
        of the list (only the count and the final/newest position) -- the
        pipe end-to-end test elsewhere in this module is what proves a
        middle column (billing_provider) is not shifted.
        """
        text = HERMES_REPORT_SH.read_text()
        matches = re.findall(r"while IFS='\|' read -r (.*?); do", text)
        main_loop_vars = [m for m in matches if m.startswith('sid model source')]
        self.assertEqual(
            len(main_loop_vars), 1,
            f'expected exactly one main read loop matching "sid model source ..."; '
            f'found {len(main_loop_vars)}'
        )
        read_vars = main_loop_vars[0].split()
        self.assertEqual(len(read_vars), 14, read_vars)
        self.assertEqual(read_vars[-1], 'user_id', read_vars)
        self.assertEqual(len(read_vars), len(_EXPECTED_SELECT_COLUMNS))

    def test_delimiter_safety_case_expression_appears_in_exactly_two_sql_sites(self):
        """The delimiter-safety `CASE WHEN user_id GLOB ...` expression
        appears in EXACTLY two places across the two scripts that emit
        `revenium meter completion` argv from `sessions.user_id`:
        hermes-report.sh's main SELECT and common.sh's `build_subscriber_map`.
        Comment lines are stripped BEFORE counting (T-61-09) -- common.sh's
        own comment describing "the SQL delimiter-safety CASE in
        hermes-report.sh's main SELECT" would otherwise itself be
        mis-parsed as an occurrence, or a future comment quoting the
        pattern for documentation could inflate the count without a second
        REAL site existing.

        Count is FOUR, not two: hermes-report.sh's main SELECT guards
        `user_id` (1), and `build_subscriber_map` guards all THREE fields it
        writes into its TAB-separated row -- `id`, `source` and `user_id` (3).
        Guarding only `user_id` there left the other two columns able to shift
        every later field (a TAB) or split one row into two (a newline), which
        let an unsafe root `source` fabricate a plausible inherited key instead
        of being rejected. Raised from 2 to 4 when that was fixed.

        Raised again, from FOUR to SIX (Phase 62 Plan 03 Task 3, SUB-05):
        `_supplement_aux_session_ctx`'s recovery SELECT (hermes-report.sh)
        gained the SAME CASE for the two new columns it now reads --
        `source` (replacing that function's own prior ad hoc Python
        `.replace()` sanitizer) and the new `user_id` -- so an
        auxiliary-only session's own subscriber resolution refuses a
        transport-unsafe value the same way every other site does, rather
        than arriving pre-sanitised into a new plausible key (T-62-15).

        MISSES: pins the NUMBER of sites, not that they are TEXTUALLY
        IDENTICAL to each other (a drifted-but-still-present copy would still
        pass this count), and not WHICH columns are guarded -- the behavioural
        proof for that is
        test_unsafe_root_source_cannot_fabricate_an_inherited_key in
        tests/test_phase61_identity_resolution.py.
        """
        needle = "GLOB '*[|'"
        total = 0
        for path in (
            SCRIPTS_DIR / 'common.sh',
            HERMES_REPORT_SH,
        ):
            text = path.read_text()
            code_only = '\n'.join(
                l for l in text.splitlines() if not l.strip().startswith('#')
            )
            total += code_only.count(needle)
        self.assertEqual(
            total, 6,
            f'expected exactly 6 delimiter-safety CASE sites '
            f'(1 in the main SELECT + 3 in build_subscriber_map + 2 in '
            f'the aux supplement\'s recovery SELECT), '
            f'counted {total}'
        )

    # `test_boundary_files_unmodified_relative_to_merge_base` -- RETIRED by
    # Phase 62 (SUB-05/D-13). It asserted `tests/fixtures/compat/`,
    # `tests/_compat_helpers.py` and `skills/revenium/scripts/api-event-report.sh`
    # were unmodified relative to the merge base with `main`; Phase 62's
    # entire purpose is to touch the first two deliberately (this plan) and
    # the third (Plan 62-02). See the module docstring's "PHASE 62 UPDATE"
    # section for the full record: what it proved, why it no longer can, and
    # what replaces it (this phase's own per-site `argv_order` equality).
    # Removed rather than edited to tolerate the drift, because a guard whose
    # premise a later phase is chartered to violate is not a guard anymore --
    # leaving it in place, weakened, would misrepresent what still holds.

    def test_run_leaves_no_new_regular_file_directly_under_state_dir(self):
        """A completed hermes-report.sh run, given an identity-bearing
        fixture, leaves no NEW regular file directly under `STATE_DIR`
        beyond the files every install already expects: `revenium-metering.log`
        and `revenium-hermes.ledger` (this run's own report output),
        `revenium-jobs.ledger` (unconditionally `touch`ed at
        hermes-report.sh:274, pre-existing and unrelated to Phase 61), and
        `aux.lock` (unconditionally `exec 8>`-opened by the auxiliary-usage
        pass's flock at hermes-report.sh:1138, also pre-existing). Proving
        D-02 ("no new state path") held for this plan's subscriber-map
        machinery specifically means proving NOTHING BEYOND this
        already-established set appeared -- the subscriber map's own
        scratch file lives under `mktemp`'s `$TMPDIR`, never `STATE_DIR`.

        MISSES: checks the TOP LEVEL of STATE_DIR only (files, not
        subdirectories like `markers/`) and only for ONE fixture shape (a
        single identity-bearing session); it does not enumerate every state
        path this repo's OTHER features might add under different
        conditions (job creation, aux metering) in the same run.
        """
        tree = _Harness(prefix='gsd-phase61-boundary-statedir-')
        try:
            before = {
                f for f in os.listdir(tree.state_dir)
                if os.path.isfile(os.path.join(tree.state_dir, f))
            }
            sid = 'p61-statedir-i'
            _seed_sessions_db(tree.state_db, [
                {'id': sid, 'source': 'slack', 'user_id': 'p61-actor-i'},
            ])
            tree.run()
            after = {
                f for f in os.listdir(tree.state_dir)
                if os.path.isfile(os.path.join(tree.state_dir, f))
            }
            new_files = after - before
            allowed = {
                'revenium-metering.log', 'revenium-hermes.ledger',
                'revenium-jobs.ledger', 'aux.lock',
            }
            self.assertTrue(
                new_files.issubset(allowed),
                f'unexpected new file(s) directly under STATE_DIR: '
                f'{new_files - allowed}'
            )
        finally:
            tree.cleanup()


if __name__ == '__main__':
    unittest.main()
