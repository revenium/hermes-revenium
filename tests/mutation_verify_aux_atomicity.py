#!/usr/bin/env python3
"""Phase 56 Plan 02 (D-13) -- fail-first mutation verification for the
auxiliary submission atomicity lock (WINDOWS entry 5).

Committed, stdlib-only, operator-invoked tool. NOT a `test_*.py` module —
the filename deliberately does not match the discovery pattern, so it never
runs as part of `python3 -m unittest discover`. Run it directly:

    python3 tests/mutation_verify_aux_atomicity.py

Modelled clause for clause on tests/mutation_verify_takeover.py -- this
repo's own established fail-first idiom -- rather than an in-suite arm,
because copying the reporter out of its own directory to mutate it would
break SCRIPT_DIR resolution.

Why this file exists in this specific phase: the project's own record is
that this billing path was "fixed" twice by narrowing the window instead of
excluding it, and review correctly rejected both times -- see
_takeover_session_owner's own header comment in hermes-report.sh, which
carries the identical lesson. This repo's own concurrency tests have also
previously repeated the error one level down (a fixture that seeds
pre/post state and runs one process, "proving" a lock that never actually
excludes anything). A concurrency test that has never been shown to go RED
against the unlocked shape is not evidence that it is closed -- it is
evidence it has never been tried. This file is that trial.

Its single axis: remove the actual `fcntl.flock` call from the exclusion's
retry loop, replacing it with a no-op that always "succeeds" without ever
taking the lock, leaving every other line of the function -- and the file's
surrounding bytes -- untouched. That is the smallest edit that faithfully
represents "the exclusion was never added": the retry loop still runs, the
descriptor is still opened and closed at every exit, the warn/defer/return
paths are all unchanged -- only the one call that actually excludes a
second process is gone. If the race tests still passed against this
mutation, that would mean they were never testing exclusion at all.

Every clause of the runner contract below mirrors mutation_verify_takeover.py
for the same reasons that file states: a mutation that cannot be applied
unambiguously (search substring not occurring EXACTLY once) is a hard error,
not a caught axis; the file's digest is checked before and after; the
verdict is read from unittest's OWN trailing status line, never by counting
matched lines and never through a shell pipeline; the named test IDs must
appear among unittest's own FAIL/ERROR headers, because "the mutation broke
SOMETHING" is not proof it broke the intended axis; a collection error or a
zero-test run is a hard error, never a pass; restoration is from a pristine
in-memory backup, never an inverse text edit; and NO_COLOR=1 is forced
because this host's ambient environment carries FORCE_COLOR and Python's
unittest honours it, silently defeating a naive string match against the
colourised output.
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

MOD = 'tests.test_phase56_aux_atomicity'
RACE = f'{MOD}.AuxAtomicityRaceTests'

# The two race-conservation assertions. AuxLockFailClosedTests and
# AuxLockDisabledArmTests are deliberately NOT targeted here: removing the
# flock call does not change the disabled arm (still returns before ever
# reaching the lock code) and does not change the fail-closed timeout shape
# (the no-op still "succeeds" immediately, so the timeout branch is simply
# never exercised) -- targeting them would assert nothing about THIS axis
# and would misrepresent what the mutation actually breaks.
TARGETED_TESTS = [
    f'{RACE}.test_exactly_one_aux_ledger_line_across_both_racers',
    f'{RACE}.test_exactly_one_operation_type_aux_invocation_across_both_racers',
]

# The exact call this mutation removes. Search for it directly in
# hermes-report.sh before trusting this constant -- a byte-for-byte
# occurrence check is exactly what apply_mutation() below performs before
# ever writing to disk.
_FLOCK_CALL = 'fcntl.flock(8, fcntl.LOCK_EX | fcntl.LOCK_NB)'
_FLOCK_NOOP = (
    'pass  # AX-56-01 MUTATED: exclusion removed -- always "succeeds" '
    'without ever taking the lock'
)

MUTATIONS = [
    dict(
        axis='AX-56-01',
        description=(
            'remove the fcntl.flock call from the auxiliary lock\'s retry '
            'loop, leaving the loop shape (and the rest of the function) '
            'byte-identical, so the acquisition always "succeeds" '
            'immediately without ever excluding a second process'
        ),
        file=HERMES_REPORT,
        search=_FLOCK_CALL,
        replace=_FLOCK_NOOP,
        tests=TARGETED_TESTS,
    ),
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
# suite as FAILED. The trailing-status contract is 'a line that STARTS with
# OK', with any parenthesised qualifier; a genuine failure prints
# 'FAILED (...)' and never starts with OK.
_TRAILING_OK_RE = re.compile(r'^OK(?: \([^)]*\))?$', re.MULTILINE)
_TRAILING_FAILED_RE = re.compile(r'^FAILED \(([^)]*)\)$', re.MULTILINE)
_FAIL_HEADER_RE = re.compile(r'^(?:FAIL|ERROR): \S+ \(([\w.]+)\)\s*$', re.MULTILINE)


def run_targeted_tests(test_ids, timeout=180):
    """Run exactly the given fully-qualified test IDs via `python3 -m
    unittest`, capturing combined stdout+stderr verbatim. NO_COLOR=1 is
    forced (see module docstring): this host's ambient FORCE_COLOR wraps
    unittest's own OK/FAILED lines in ANSI escapes that a naive string match
    silently fails to find."""
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
    finally:
        restore_from_backup(target, backups)

    # Restore-verification: the SAME targeted tests must pass against the
    # now-restored tree, or a broken restore silently poisons the result.
    post = run_targeted_tests(tests)
    if 'hard_error' in post or post['verdict'] != 'OK':
        raise MutationVerifyError(
            f'[{axis}] restore verification FAILED — targeted tests do not pass '
            f'against the restored tree. Aborting.\n{post.get("output", post.get("hard_error"))}')

    return {
        'axis': axis,
        'description': row['description'],
        'tests': tests,
        'expected': 'FAIL',
        'observed': result['verdict'],
        'targeted_present': targeted_present,
        'pass': row_pass,
    }


def print_table(rows):
    print()
    print('=' * 100)
    print('AUX ATOMICITY MUTATION VERIFICATION RESULTS')
    print('=' * 100)
    for r in rows:
        print()
        print(f'Axis:              {r["axis"]}')
        print(f'Description:       {r["description"]}')
        print(f'Targeted tests:    {", ".join(r["tests"])}')
        print(f'Expected verdict:  {r["expected"]}')
        print(f'Observed verdict:  {r["observed"]}')
        print(f'Targeted IDs among reported failures: {r["targeted_present"]}')
        print(f'ROW RESULT:        {"PASS" if r["pass"] else "FAIL"}')
    print()
    print('=' * 100)


def main():
    backups = load_pristine_backups(TARGET_FILES)

    results = []
    aborted = False
    for row in MUTATIONS:
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
    print('Re-running the named race tests once more (final integrity check)...')
    final = run_targeted_tests(TARGETED_TESTS)
    final_ok = final.get('verdict') == 'OK'
    print(final.get('output', final.get('hard_error', ''))[-2000:])
    print(f'Final targeted re-run: {"OK" if final_ok else "FAILED"}')

    print()
    if any_row_failed:
        print('RESULT: the mutation did NOT drive the named tests RED as expected. FAILING.',
              file=sys.stderr)
    if not tree_clean:
        print('RESULT: tree is not byte-identical after the run. FAILING.', file=sys.stderr)
    if not final_ok:
        print('RESULT: the restored tree did not drive the named tests GREEN again. FAILING.',
              file=sys.stderr)

    if any_row_failed or not tree_clean or not final_ok:
        sys.exit(1)

    print('RESULT: the unlocked mutation drove the named concurrency tests RED, and the '
          'restored file drove them GREEN again. Exiting 0.')
    sys.exit(0)


if __name__ == '__main__':
    main()
