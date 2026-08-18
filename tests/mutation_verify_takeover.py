#!/usr/bin/env python3
"""quick-260818-0in — per-axis mutation verification for the mode-aware
legacy takeover.

Committed, stdlib-only, operator-invoked tool. NOT a `test_*.py` module —
the filename deliberately does not match the discovery pattern, so it
never runs as part of `python3 -m unittest discover`. Run it directly:

    python3 tests/mutation_verify_takeover.py

Treated as production code on a billing path. This phase's own history
records four instrumentation bugs that produced output which merely
LOOKED like a result: `pgrep -f` matching its own command line, two poll
loops with wrong exit conditions, and `grep -c ... || echo 0` printing two
zeros so a `!= "0"` check passed on zero rows. Every clause of the runner
contract below exists to close one of those failure classes:

  - The mutation search substring must occur EXACTLY once in the target
    file before it is applied. Zero or more than one is a hard error that
    aborts the run — a mutation that silently fails to apply produces a
    green "the guard caught it" result that is actually "nothing changed".
  - The file's digest is checked before and after the write, so a
    replace() that is a silent no-op (e.g. a typo in the search string
    that still matched zero times, which the count-exactly-one check
    already catches, but belt-and-suspenders) cannot pass unnoticed.
  - The verdict is read from unittest's OWN trailing status line ("OK" or
    "FAILED (...)"), never by counting matched lines, never through a
    shell pipeline, and never through a construct (like `grep -c ... ||
    echo 0`) that can print a value when its input is empty. Python's
    subprocess + a direct string match on unittest's own summary line is
    the whole of the parsing surface.
  - Each targeted test ID must appear among the FAILURE headers unittest
    itself printed (`FAIL: <method> (<dotted.path>)` /
    `ERROR: <method> (<dotted.path>)`). "The mutation broke SOMETHING" is
    not accepted as proof that it broke the axis it was supposed to.
  - A collection error, an import error, or a run that reports zero tests
    is a HARD ERROR, never a pass and never counted as the expected
    failure — an axis whose test module failed to even import would
    otherwise look identical to an axis whose guard correctly broke.
  - Every mutation is restored from a PRISTINE, in-memory backup taken
    once at the very start — never by re-applying an inverse text edit,
    which could drift from the original byte-for-byte. After restoring,
    the SAME targeted tests are re-run and required to PASS before the
    next row runs, so a restore that silently failed cannot poison every
    later axis's result.
  - `NO_COLOR=1` is forced into the subprocess environment. This host's
    ambient environment carries `FORCE_COLOR=3`, and Python 3.13+'s
    unittest honors it — every "OK" / "FAIL" / trailing status line comes
    back wrapped in ANSI escape codes unless explicitly disabled. Measured
    directly while building this file: the naive parser (matching the
    literal strings "OK" / "FAILED (...)") silently found NOTHING against
    the colorized output, which is exactly the "produces a result that
    looks like proof" failure class this file exists to close for
    everything else. Do not remove this without re-verifying against a
    colorized environment.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERMES_REPORT = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
TARGET_FILES = [HERMES_REPORT]

MOD = 'tests.test_mode_aware_legacy_takeover'
TRACER = f'{MOD}.ModeAwareTakeoverTracerTests'
MODE_RES = f'{MOD}.ModeResolutionTests'
BILL_FLOOR = f'{MOD}.BillForwardAndFloorTests'
GUARD_COMP = f'{MOD}.GuardCompositionTests'
ORDERING = f'{MOD}.OrderingTicksOscillationTests'
PROFILES = f'{MOD}.ProfilesConcurrencyRetentionTests'
REGRESSION = f'{MOD}.RegressionGuardTests'

A1 = f'{TRACER}.test_a1_mode_live_event_owned_session_still_defers_unchanged'
A2 = f'{TRACER}.test_a2_mode_shadow_takes_over_records_the_floor_and_ships_nothing_on_the_takeover_tick'
A3 = f'{MODE_RES}.test_a3_mode_unset_no_env_no_config_resolves_to_shadow_and_takes_over'
A4 = f'{MODE_RES}.test_a4_mode_invalid_falls_back_to_shadow_takes_over_and_warns_once'
A5 = f'{MODE_RES}.test_a5_mode_from_config_json_env_unset_a_config_sourced_live_defers'
A6 = f'{TRACER}.test_a6_growth_after_takeover_bills_only_the_growth_not_the_cumulative_total'
A7 = f'{BILL_FLOOR}.test_a7_a_second_growth_after_the_first_bills_only_that_growth_too'
A10 = f'{BILL_FLOOR}.test_a10_a_higher_pre_existing_floor_is_preserved_after_the_flip'
A11 = f'{TRACER}.test_a11_no_takeover_while_legacy_emission_is_disabled_record_untouched'
A12b = f'{GUARD_COMP}.test_a12b_the_branch_that_consumes_empty_takeover_output_defers_rather_than_bills'
A14 = f'{ORDERING}.test_a14_mode_shadow_cron_order_takes_over_and_still_yields_exactly_one_biller'
A15 = f'{ORDERING}.test_a15_repeated_ticks_over_a_taken_over_record_ship_nothing_extra_and_warn_once'
A16 = f'{TRACER}.test_a16_a_live_event_shipper_after_the_takeover_ships_nothing_the_flip_is_one_way'
A18 = f'{PROFILES}.test_a18_two_legacy_runs_racing_an_event_owned_session_in_shadow_conserve'
A19 = f'{PROFILES}.test_a19_after_a_takeover_the_owners_dir_holds_one_entry_pruned_by_state_db_presence'
A20 = f'{REGRESSION}.test_a20_the_54_dual_ledger_migration_is_unchanged'
A21 = f'{TRACER}.test_a21_disengaged_install_meters_byte_identically_and_creates_no_ownership_state'
A23 = f'{REGRESSION}.test_a23_own_04_claim_fail_direction_is_unchanged_by_the_takeover'
A24 = f'{REGRESSION}.test_a24_the_takeover_primitive_can_only_ever_write_the_legacy_literal'
A25 = f'{PROFILES}.test_a25_a_stale_snapshot_baseline_is_floored_out_by_the_publish_instant_reread'
# The race window's own assertion. It lives in a separate module because it
# needs a PATH shim to stall one racer between its OWNER=event observation
# and its replace -- A18 cannot host it, since A18's whole method is to seed
# the post-takeover state and avoid real thread timing.
RACE = 'tests.test_ax14_takeover_race_window.TakeoverRaceWindowTests'
A26 = f'{RACE}.test_late_replace_with_a_failed_ax21_reread_lowers_the_floor'

# ---------------------------------------------------------------------------
# The mutation table. One row per axis (per the runner contract), except
# AX-20 and AX-13 (see STRUCTURAL_AXES below) and AX-17's golden half (the
# AX-17 row targets A21's "no ownership state created" assertion, not its
# byte-for-byte argv comparison against the golden fixture).
# ---------------------------------------------------------------------------

#
# quick-260818-jbl (E-11): _GUARD_IF's ORIGINAL search text
# ('"${LEGACY_COMPLETIONS_SKIP}" == "true"') went stale when #57
# (quick-260818-f1g) changed the takeover branch's guard from the
# fleet-global LEGACY_COMPLETIONS_SKIP boolean to the per-session
# sid_legacy_suppressed local. Measured this session: the old constant
# occurred ZERO times in hermes-report.sh, so apply_mutation's
# `count != 1` contract correctly hard-errored on rows AX-02/03/04/08/10
# rather than silently reporting them as caught. mutation_verify_takeover.py
# is deliberately NOT under `test_*.py` discovery (see its own module
# docstring), so the 507-test baseline never caught the drift — only running
# this file directly (or, as here, a later quick task re-extracting its own
# anchors) surfaces it. Updated to the line as it exists in the source today.
_GUARD_IF = ('if [[ "${EVENT_PATH_LIVE}" == "true" || '
             '"${sid_legacy_suppressed}" == "true" ]]; then')
_FLOOR_IF = ('if [[ "${owner_baseline}" =~ ^[0-9]+$ && '
             '"${owner_baseline}" -gt 0 ]]; then')
_MAX_LINE = 'new_baseline = max(requested, known, live_total, on_disk, 0)'
_LEGACY_WRITE = '_tfh.write("legacy\\n")'
_ONDISK_READ_OPEN = '    with open(path) as _rfh:'
_TAKEOVER_PATH_BLOCK = (
    "sid = os.environ.get('TAKEOVER_SID', '')\n"
    "\n"
    "if not owners_dir or not sid:\n"
    "    raise SystemExit(0)\n"
    "\n"
    "# T-OWN-01's derivation, mirrored byte-for-byte — no second rule anywhere.\n"
    "name = sid.replace('/', '_').replace('\\x00', '_')[:200]\n"
    "if not name:\n"
    "    raise SystemExit(0)\n"
    "path = os.path.join(owners_dir, name)"
)
_AX21_REREAD_BLOCK = (
    'live_total = 0\n'
    'try:\n'
    '    import sqlite3\n'
    '    if state_db and os.path.isfile(state_db):\n'
    '        uri = f"file:{state_db}?mode=ro"\n'
    '        with sqlite3.connect(uri, uri=True) as conn:\n'
    '            row = conn.execute(\n'
    '                "SELECT COALESCE(input_tokens,0) + COALESCE(output_tokens,0) "\n'
    '                "FROM sessions WHERE id = ?",\n'
    '                (sid,),\n'
    '            ).fetchone()\n'
    '            if row is not None:\n'
    '                live_total = _nonneg_int(row[0])\n'
    'except Exception:\n'
    '    live_total = 0'
)
_AX21_QUERY = (
    '                "SELECT COALESCE(input_tokens,0) + COALESCE(output_tokens,0) "\n'
    '                "FROM sessions WHERE id = ?",'
)
_AX21_QUERY_WRONG_UNITS = (
    '                "SELECT COALESCE(input_tokens,0) "\n'
    '                "FROM sessions WHERE id = ?",'
)

MUTATIONS = [
    dict(axis='AX-01', description='invert the liveness check',
         file=HERMES_REPORT,
         search='if [[ "${_event_metering_mode_resolved}" == "live" ]]; then',
         replace='if [[ "${_event_metering_mode_resolved}" != "live" ]]; then',
         tests=[A1]),
    dict(axis='AX-02', description='force the deferral unconditionally (mode=shadow case)',
         file=HERMES_REPORT, search=_GUARD_IF, replace='if true; then',
         tests=[A2]),
    dict(axis='AX-03', description='force the deferral unconditionally (mode-unset case)',
         file=HERMES_REPORT, search=_GUARD_IF, replace='if true; then',
         tests=[A3]),
    dict(axis='AX-04', description='force the deferral unconditionally (mode-invalid case)',
         file=HERMES_REPORT, search=_GUARD_IF, replace='if true; then',
         tests=[A4]),
    dict(axis='AX-05', description="pass the post-source defaulted variable instead of the raw capture",
         file=HERMES_REPORT,
         search=('resolve_switch_setting "${_EVENT_METERING_MODE_ENV_RAW}" '
                 '"eventMeteringMode" "shadow" "shadow" "live"'),
         replace=('resolve_switch_setting "${REVENIUM_EVENT_METERING_MODE}" '
                  '"eventMeteringMode" "shadow" "shadow" "live"'),
         tests=[A5]),
    dict(axis='AX-06', description='make the takeover record a zero floor',
         file=HERMES_REPORT, search=_MAX_LINE, replace='new_baseline = 0',
         tests=[A6, A7]),
    dict(axis='AX-07', description='replace the maximum with a plain assignment',
         file=HERMES_REPORT, search=_MAX_LINE, replace='new_baseline = requested',
         tests=[A10]),
    dict(axis='AX-08', description='drop the disabled-legacy disjunct',
         file=HERMES_REPORT, search=_GUARD_IF,
         replace='if [[ "${EVENT_PATH_LIVE}" == "true" ]]; then',
         tests=[A11]),
    dict(axis='AX-09', description='make the empty-output branch bill instead of defer',
         file=HERMES_REPORT,
         search=('              session_event_owned="true"\n'
                 '              ((takeover_unavailable_count++)) || true'),
         replace=('              session_event_owned="false"\n'
                  '              ((takeover_unavailable_count++)) || true'),
         tests=[A12b]),
    dict(axis='AX-10', description='force the deferral unconditionally (cron-order/shadow case)',
         file=HERMES_REPORT, search=_GUARD_IF, replace='if true; then',
         tests=[A14]),
    dict(axis='AX-11', description='remove the floor application relative to the growth guard',
         file=HERMES_REPORT, search=_FLOOR_IF, replace='if false; then',
         tests=[A15]),
    dict(axis='AX-12', description='make the takeover write the event literal instead',
         file=HERMES_REPORT, search=_LEGACY_WRITE, replace='_tfh.write("event\\n")',
         tests=[A16]),
    dict(axis='AX-14', description='remove the floor application (legacy-vs-legacy conservation)',
         file=HERMES_REPORT, search=_FLOOR_IF, replace='if false; then',
         tests=[A18]),
    dict(axis='AX-15', description='make the takeover write a sibling file rather than replacing the record',
         file=HERMES_REPORT, search=_TAKEOVER_PATH_BLOCK,
         replace=_TAKEOVER_PATH_BLOCK.replace(
             'path = os.path.join(owners_dir, name)',
             "path = os.path.join(owners_dir, name + '.takeover')"),
         tests=[A19]),
    dict(axis='AX-16', description='flip the dual-ledger resolution to the event side',
         file=HERMES_REPORT,
         search='dual_ledger="true"\n        claim_side="legacy"',
         replace='dual_ledger="true"\n        claim_side="event"',
         tests=[A20]),
    dict(axis='AX-17', description='force the engagement gate always active',
         file=HERMES_REPORT,
         search='OWNERSHIP_PROTOCOL_ACTIVE="false"',
         replace='OWNERSHIP_PROTOCOL_ACTIVE="true"',
         tests=[A21]),
    dict(axis='AX-18', description="break OWN-04's fail-open direction on a claim failure",
         file=HERMES_REPORT,
         search='((claim_unavailable_count++)) || true',
         replace='((claim_unavailable_count++)) || true\n        session_event_owned="true"',
         tests=[A23]),
    dict(axis='AX-19', description='make the takeover write the event literal instead (one-way invariant)',
         file=HERMES_REPORT, search=_LEGACY_WRITE, replace='_tfh.write("event\\n")',
         tests=[A24]),
]

# AX-21 gets its own three rows, mutated separately from AX-14's, each
# required to fail ONLY the AX-21 test and never AX-14's — asserted
# explicitly via `non_overlap_test` below, because "AX-21's mutation broke
# something" and "AX-21's mutation broke AX-21's assertion" are the exact
# distinction this file exists to preserve.
AX21_MUTATIONS = [
    dict(axis='AX-21a', description='delete the publish-instant re-read entirely (floor falls back to the stale snapshot)',
         file=HERMES_REPORT, search=_AX21_REREAD_BLOCK, replace='live_total = 0',
         tests=[A25], non_overlap_test=A18),
    dict(axis='AX-21b', description='drop the re-read from the max() while leaving the query in place',
         file=HERMES_REPORT, search=_MAX_LINE,
         replace='new_baseline = max(requested, known, on_disk, 0)',
         tests=[A25], non_overlap_test=A18),
    dict(axis='AX-21c', description='change the summed columns so the value is real but in the wrong units',
         file=HERMES_REPORT, search=_AX21_QUERY, replace=_AX21_QUERY_WRONG_UNITS,
         tests=[A25], non_overlap_test=A18),
]

# AX-14 (the race window) gained a real mutation surface when the race fix
# landed. Before it, AX-14 was asserted only by A18 -- which seeds the
# post-takeover state and runs ONE reporter, so it never opens the window.
# These two rows target the on-disk record re-read specifically: 14a removes
# the term from the max(), 14b keeps the term but breaks the read so it
# always yields 0, which is the exact production failure mode (the except
# branch) that lets a stale `known` win.
AX14_RACE_MUTATIONS = [
    dict(axis='AX-14a', description='drop the on-disk record re-read from the max() (loser republishes its stale floor)',
         file=HERMES_REPORT, search=_MAX_LINE,
         replace='new_baseline = max(requested, known, live_total, 0)',
         tests=[A26], non_overlap_test=A18),
    dict(axis='AX-14b', description='keep the term but make the record read always fail (exercises the except path)',
         file=HERMES_REPORT, search=_ONDISK_READ_OPEN,
         replace="    with open(path + '.nonexistent-for-mutation') as _rfh:",
         tests=[A26], non_overlap_test=A18),
]

STRUCTURAL_AXES = [
    dict(axis='AX-20', note=(
        "Argued structurally per the plan, not asserted in-tree: the takeover fires "
        "only when the mode is not 'live', and an event shipper of ANY version ships "
        "nothing while the mode is not 'live' -- so this change adds no new deploy-skew "
        "hazard. A1 and A16 are its in-tree proxies. PR #54's rollout ordering rule "
        "(every profile updated, verified by checksum, before any profile flips "
        "shadow->live) is unchanged and is restated in docs/event-metering.md.")),
    dict(axis='AX-13', note=(
        "No mutation constructed, and this is a deviation from the plan's own mutation "
        "list worth stating plainly: hermes-report.sh's mode resolution and takeover "
        "read exactly three profile-scoped artifacts -- CONFIG_FILE, OWNERS_DIR, "
        "STATE_DB -- each a SINGLE fixed path derived from HERMES_HOME / "
        "REVENIUM_STATE_DIR, with no glob, sweep, or wildcard anywhere in this quick "
        "task's new code. There is no 'engagement-gate glob' surface in the mode-aware "
        "guard to widen. (The PRE-EXISTING quick-260817-tfe engagement gate does use a "
        "glob -- OWNERSHIP_PROTOCOL_ACTIVE's own probe -- but mutating it does not "
        "change WHICH directory the claim or takeover read, only whether the protocol "
        "activates, and test A17's fixture already activates the protocol through a "
        "real owners record; the mutation would be a no-op against that test. "
        "Fabricating a mutation that does not correspond to a real vulnerable code path "
        "would misrepresent coverage rather than provide it -- so A17 (the profiles "
        "test) is retained as a construction-based proof, argued the same way "
        "test_phase32_shadow_readout.py's CrossProfileIsolationTests already argues the "
        "event path's own spool-directory isolation.")),
]


class MutationVerifyError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pristine_backups(files):
    return {f: f.read_bytes() for f in files}


def restore_from_backup(target: Path, backups: dict):
    target.write_bytes(backups[target])


def apply_mutation(target: Path, search: str, replace: str):
    text = target.read_text()
    count = text.count(search)
    if count != 1:
        raise MutationVerifyError(
            f'search substring occurs {count} time(s) in {target} (must be EXACTLY 1) — '
            f'a mutation that cannot be applied unambiguously produces a green result '
            f'that looks like proof, not proof.\nsearch={search!r}')
    before_digest = sha256_of(target)
    new_text = text.replace(search, replace, 1)
    target.write_text(new_text)
    after_digest = sha256_of(target)
    if after_digest == before_digest:
        raise MutationVerifyError(
            f'{target} digest did not change after the mutation was applied — the write '
            f'silently no-op\'d')


_RAN_RE = re.compile(r'^Ran (\d+) tests? in', re.MULTILINE)
# unittest's success line is NOT always a bare 'OK': it becomes
# 'OK (expected failures=1)' or 'OK (skipped=2)' as soon as the suite
# contains a decorated test. A '^OK$' anchor silently reports a PASSING
# suite as FAILED -- measured, not theorised: it did exactly that when
# test_ax14_takeover_race_window's expectedFailure control landed. The
# trailing-status contract is 'a line that STARTS with OK', with any
# parenthesised qualifier; a genuine failure prints 'FAILED (...)' and
# never starts with OK.
_TRAILING_OK_RE = re.compile(r'^OK(?: \([^)]*\))?$', re.MULTILINE)
_TRAILING_FAILED_RE = re.compile(r'^FAILED \(([^)]*)\)$', re.MULTILINE)
_FAIL_HEADER_RE = re.compile(r'^(?:FAIL|ERROR): \S+ \(([\w.]+)\)\s*$', re.MULTILINE)


def run_targeted_tests(test_ids, timeout=180):
    """Run exactly the given fully-qualified test IDs via `python3 -m
    unittest`, capturing combined stdout+stderr verbatim. NO_COLOR=1 is
    forced (see module docstring): this host's ambient FORCE_COLOR=3
    wraps unittest's own OK/FAILED lines in ANSI escapes that a naive
    string match silently fails to find."""
    env = dict(os.environ)
    env['NO_COLOR'] = '1'
    env.pop('FORCE_COLOR', None)
    cmd = [sys.executable, '-m', 'unittest', '-v', *test_ids]
    try:
        result = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {'hard_error': f'timeout running {test_ids}: {exc}'}

    combined = (result.stdout or '') + (result.stderr or '')

    ran_match = _RAN_RE.search(combined)
    if ran_match is None or int(ran_match.group(1)) == 0:
        return {'hard_error': (
            f'could not find a "Ran N tests" line, or it reported zero tests, for '
            f'{test_ids} — this is a HARD ERROR (import/collection failure), never a '
            f'pass or a caught mutation.\n--- combined output ---\n{combined}')}

    # THE verdict read: unittest's OWN trailing status line, direct string
    # match only — no shell pipeline, no counting, no construct that can
    # emit a value on empty input.
    if _TRAILING_OK_RE.search(combined):
        verdict_status = 'OK'
    else:
        failed_match = _TRAILING_FAILED_RE.search(combined)
        if failed_match is None:
            return {'hard_error': (
                f'could not find unittest\'s own trailing "OK" or "FAILED (...)" status '
                f'line for {test_ids} — treating as a hard error rather than guessing.\n'
                f'--- combined output ---\n{combined}')}
        verdict_status = 'FAILED'

    failed_ids = set(_FAIL_HEADER_RE.findall(combined))
    return {
        'ran': int(ran_match.group(1)),
        'verdict': verdict_status,
        'failed_ids': failed_ids,
        'output': combined,
        'returncode': result.returncode,
    }


def run_one_mutation_row(row, backups):
    axis = row['axis']
    target = row['file']
    tests = row['tests']

    apply_mutation(target, row['search'], row['replace'])
    try:
        result = run_targeted_tests(tests)
        if 'hard_error' in result:
            raise MutationVerifyError(f'[{axis}] {result["hard_error"]}')

        targeted_present = all(t in result['failed_ids'] for t in tests)
        row_pass = (result['verdict'] == 'FAILED') and targeted_present

        overlap_pass = None
        if row.get('non_overlap_test'):
            overlap_result = run_targeted_tests([row['non_overlap_test']])
            if 'hard_error' in overlap_result:
                raise MutationVerifyError(
                    f'[{axis}] hard error checking non-overlap against '
                    f'{row["non_overlap_test"]}: {overlap_result["hard_error"]}')
            overlap_pass = overlap_result['verdict'] == 'OK'
            row_pass = row_pass and overlap_pass
    finally:
        restore_from_backup(target, backups)

    # Restore-verification: the SAME targeted tests must pass against the
    # now-restored tree, or a broken restore silently poisons every axis
    # that runs after this one.
    post = run_targeted_tests(tests)
    if 'hard_error' in post or post['verdict'] != 'OK':
        raise MutationVerifyError(
            f'[{axis}] restore verification FAILED — targeted tests do not pass '
            f'against the restored tree. Aborting: a broken restore invalidates every '
            f'later row.\n{post.get("output", post.get("hard_error"))}')

    return {
        'axis': axis,
        'description': row['description'],
        'tests': tests,
        'expected': 'FAIL',
        'observed': result['verdict'],
        'targeted_present': targeted_present,
        'overlap_pass': overlap_pass,
        'non_overlap_test': row.get('non_overlap_test'),
        'pass': row_pass,
    }


def print_table(rows):
    print()
    print('=' * 100)
    print('PER-AXIS MUTATION VERIFICATION RESULTS')
    print('=' * 100)
    for r in rows:
        print()
        print(f'Axis:              {r["axis"]}')
        print(f'Description:       {r["description"]}')
        print(f'Targeted tests:    {", ".join(r["tests"])}')
        print(f'Expected verdict:  {r["expected"]}')
        print(f'Observed verdict:  {r["observed"]}')
        print(f'Targeted IDs among reported failures: {r["targeted_present"]}')
        if r['non_overlap_test'] is not None:
            print(f'Non-overlap check ({r["non_overlap_test"]} must PASS): '
                  f'{"PASS" if r["overlap_pass"] else "FAIL"}')
        print(f'ROW RESULT:        {"PASS" if r["pass"] else "FAIL"}')
    print()
    print('-' * 100)
    for note in STRUCTURAL_AXES:
        print(f'{note["axis"]} (structural, no mutation):')
        print(f'  {note["note"]}')
        print()
    print('=' * 100)


def main():
    backups = load_pristine_backups(TARGET_FILES)

    all_rows = list(MUTATIONS) + list(AX21_MUTATIONS) + list(AX14_RACE_MUTATIONS)
    results = []
    aborted = False
    for row in all_rows:
        try:
            results.append(run_one_mutation_row(row, backups))
        except MutationVerifyError as exc:
            # Ensure the file is restored even on a hard error, then abort
            # the whole run rather than continuing on unreliable ground.
            for f in TARGET_FILES:
                restore_from_backup(f, backups)
            print(f'\nHARD ERROR on axis {row["axis"]}: {exc}\n', file=sys.stderr)
            aborted = True
            break

    print_table(results)

    if aborted:
        print('ABORTED — see hard error above. Exiting non-zero.', file=sys.stderr)
        sys.exit(1)

    any_row_failed = any(not r['pass'] for r in results)

    # Post-run integrity: the tree must be byte-identical to its pre-run
    # state. Checked AFTER the table, as required.
    print('Verifying tree is byte-identical to its pre-run state (git diff --quiet)...')
    diff_result = subprocess.run(
        ['git', 'diff', '--quiet', '--'] + [str(f) for f in TARGET_FILES],
        cwd=str(ROOT),
    )
    tree_clean = diff_result.returncode == 0
    print(f'git diff --quiet over target files: {"CLEAN" if tree_clean else "DIRTY"}')
    if not tree_clean:
        subprocess.run(['git', 'diff', '--'] + [str(f) for f in TARGET_FILES], cwd=str(ROOT))

    print()
    print('Running the full suite once (final integrity check)...')
    env = dict(os.environ)
    env['NO_COLOR'] = '1'
    env.pop('FORCE_COLOR', None)
    full_suite = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=900,
    )
    full_combined = (full_suite.stdout or '') + (full_suite.stderr or '')
    full_ran_match = _RAN_RE.search(full_combined)
    full_ok = bool(_TRAILING_OK_RE.search(full_combined))
    print(full_combined[-2000:])
    print(f'Full suite: {"OK" if full_ok else "FAILED"}'
          + (f', {full_ran_match.group(1)} tests' if full_ran_match else ', UNKNOWN COUNT'))

    print()
    if any_row_failed:
        print('RESULT: at least one axis did NOT fail as expected. FAILING.', file=sys.stderr)
    if not tree_clean:
        print('RESULT: tree is not byte-identical after the run. FAILING.', file=sys.stderr)
    if not full_ok:
        print('RESULT: full suite did not report OK after the run. FAILING.', file=sys.stderr)

    if any_row_failed or not tree_clean or not full_ok:
        sys.exit(1)

    print('RESULT: every axis failed as expected, the tree is byte-identical, and the '
          'full suite passes. Exiting 0.')
    sys.exit(0)


if __name__ == '__main__':
    main()
