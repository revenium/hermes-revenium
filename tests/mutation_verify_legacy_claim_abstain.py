#!/usr/bin/env python3
"""quick-260818-jbl — per-axis mutation verification for the legacy-claim
abstention (CLAIM-01..05).

Committed, stdlib-only, operator-invoked tool. NOT a `test_*.py` module —
the filename deliberately does not match the discovery pattern, so it never
runs as part of `python3 -m unittest discover`. Run it directly:

    python3 tests/mutation_verify_legacy_claim_abstain.py

Treated as production code on a billing path, for the identical reasons
tests/mutation_verify_takeover.py's own module docstring states -- this
file imports its runner contract (_TRAILING_OK_RE, NO_COLOR=1 forcing,
apply_mutation's count-exactly-one check, restore-from-pristine-backup,
targeted-test-ID-among-failures) directly from that module rather than
re-implementing it, so the trailing-status-line parsing contract exists in
exactly one place. See that module's docstring for the full rationale.

DEVIATION FROM THE PLAN, RECORDED HERE (also in the SUMMARY): PLAN.md's
axis register specifies AX-Q4 and AX-Q5 as both mutating `_ABSTAIN_IF` to
the literal `if true; then`. Built and run as literally specified, that
single mutation forces claim_abstain="true" UNCONDITIONALLY -- which also
defeats AX-Q4's own dual-ledger resolution (the claim block never runs, so
AX-Q4's test fails too), directly contradicting AX-Q5's stated
`non_overlap_test = AX-Q4's test` requirement (Q4 must still PASS while
mutating for Q5). Verified empirically before writing this file. Two
narrower, axis-specific mutations replace the shared one:
  - AX-Q4 drops BOTH ledger-presence conjuncts (legacy_rows_present AND
    event_rows_present), which affects a dual-ledger session (both present)
    without affecting an unsuppressed session (Q5's fixture is unaffected
    because ITS assertion never depends on those conjuncts individually).
  - AX-Q5 drops ONLY the suppression conjunct, which affects an unsuppressed
    session (Q5's fixture) without affecting Q4's dual-ledger session (Q4's
    OTHER two conjuncts, still present, are already false for a dual-ledger
    fixture regardless of suppression).
Each row's `note` restates this narrower target. The two mutations are
individually MORE PRECISE proxies for their axes than the shared one the
plan specified, and preserve the plan's own non-overlap requirement, which
the literal shared mutation could not.

A SECOND deviation, found and fixed by this file's own construction, not
merely reported: applying AX-08's PRE-EXISTING mutation row in
mutation_verify_takeover.py (drop the disabled-legacy disjunct from the
mode-aware takeover's inner guard) against the freshly-hoisted
`claim_abstain` outer guard showed the targeted test
(test_a11_no_takeover_while_legacy_emission_is_disabled_record_untouched)
observing verdict=OK instead of FAILED -- the mutation's own test no longer
caught it. Root cause: claim_abstain's original three-conjunct predicate
(sid_legacy_suppressed + legacy_rows_present + event_rows_present) did not
account for a session that already HAS an owner record (of any owner) but
happens to have zero rows in either billing ledger -- exactly A11's
fixture, which seeds an `event` record directly. The outer guard then
skipped the ENTIRE claim-resolution block, including the mode-aware
takeover's own inner guard, making AX-08's mutation surface unreachable
under A11's fixture. Fixed in hermes-report.sh by adding a fourth
conjunct, `owner_record_absent`, so abstention only fires for a session
with NO existing record -- the plan's own stated intent ("no record yet is
the initial state of every session"), made an explicit, checked condition
instead of an unstated assumption. Verified this restores AX-08's
reachability (see the full suite run in the executor's report) without
changing billing behavior on any axis (the emission guard's own
sid_legacy_suppressed conjunct already independently blocks emission in
every scenario this predicate covers).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERMES_REPORT = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
PRUNE_MARKERS = ROOT / 'skills' / 'revenium' / 'scripts' / 'prune-markers.sh'
TARGET_FILES = [HERMES_REPORT, PRUNE_MARKERS]

sys.path.insert(0, str(ROOT))

from tests.mutation_verify_takeover import (  # noqa: E402
    MutationVerifyError,
    apply_mutation,
    load_pristine_backups,
    restore_from_backup,
    run_targeted_tests,
)

import subprocess  # noqa: E402
import os  # noqa: E402

MOD = 'tests.test_legacy_claim_abstention'

Q1 = f'{MOD}.LiveDefectTracerTests.test_q1_suppressed_new_session_is_not_claimed_by_legacy_and_is_billed_by_the_event_path'
Q2 = f'{MOD}.SuppressedNonAbstainingLegsTests.test_q2_suppressed_with_legacy_rows_only_legacy_retains_ownership_and_does_not_abstain'
Q3 = f'{MOD}.SuppressedNonAbstainingLegsTests.test_q3_suppressed_with_event_rows_only_resolution_table_still_backfills_event'
Q4 = f'{MOD}.SuppressedNonAbstainingLegsTests.test_q4_suppressed_dual_ledger_still_resolves_to_legacy_with_its_catch_up_baseline_and_one_warn'
Q5 = f'{MOD}.NotSuppressedByteIdenticalTests.test_q5_unsuppressed_claim_is_byte_identical_to_the_golden_even_with_the_protocol_engaged'
Q6 = f'{MOD}.PerSessionRetainedTests.test_q6_two_sessions_one_run_retained_sid_is_claimed_the_other_abstains'
Q7 = f'{MOD}.SettleGateTests.test_q7_a_session_deferred_by_the_settle_gate_still_abstains_on_the_tick_that_reaches_the_claim'
Q8 = f'{MOD}.RecoveryAndModeRevertTests.test_q8_re_enabling_legacy_after_an_abstention_claims_and_bills_from_a_clean_baseline'
Q9 = f'{MOD}.RecoveryAndModeRevertTests.test_q9_the_takeover_still_fires_with_its_floor_after_an_abstention'
Q10 = f'{MOD}.RetentionPruningTests.test_q10_abstention_creates_nothing_to_prune_and_a_live_record_survives'
Q11 = f'{MOD}.ConcurrencyOrderingTests.test_q11_either_stage_order_yields_exactly_one_biller_and_the_abstain_branch_publishes_nothing'
Q13A = f'{MOD}.DisengagedInstallTests.test_q13a_disengaged_install_is_byte_identical_to_the_markerless_golden_and_creates_no_ownership_state'
Q14 = f'{MOD}.SourcePropertyTests.test_q14_the_abstain_predicate_and_the_emission_guard_read_the_same_local'
Q16 = f'{MOD}.BoundedRecoveryWarnTests.test_q16_abstention_recovery_is_bounded_by_spool_retention_and_warns_while_the_event_path_is_not_live'
Q17 = f'{MOD}.JobsGatingTests.test_q17_abstention_does_not_change_job_creation_or_outcome_gating'

# ---------------------------------------------------------------------------
# Anchors, extracted byte-for-byte from the source this session, not
# transcribed from PLAN.md. Re-verified unique (count == 1 in
# hermes-report.sh) immediately before this file was written.
# ---------------------------------------------------------------------------

_ABSTAIN_IF = (
    'if [[ "${sid_legacy_suppressed}" == "true" && '
    '"${legacy_rows_present}" == "false" && '
    '"${event_rows_present}" == "false" && '
    '"${owner_record_absent}" == "true" ]]; then'
)
_OUTER_GUARD = (
    'if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" && '
    '"${claim_abstain}" != "true" ]]; then'
)
_ABSTAIN_SET = 'claim_abstain="true"\n      ((claim_abstained_count++)) || true'
_ABSTAIN_REPORT = 'if [[ "${EVENT_PATH_LIVE}" == "true" ]]; then'
_EMISSION_GUARD = (
    'if [[ "${sid_legacy_suppressed}" != "true" && '
    '"${session_event_owned}" != "true" ]]; then'
)
_ENGAGEMENT_DEFAULT = 'OWNERSHIP_PROTOCOL_ACTIVE="false"'
_LIVE_SET_INSERT = 'live.add(_owner_record_name(str(sid)))'
_PRECHECK_JOBS_IF = (
    'if [[ "${JOBS_CLI_CAPABLE}" == "true" && '
    '-f "${session_markers_dir}/${sid}.jsonl" ]]; then'
)
_MAIN_JOBS_IF = (
    'if [[ "${JOBS_CLI_CAPABLE}" == "true" && -n "${jobs_json}" && '
    '"${jobs_json}" != "[]" ]]; then'
)

MUTATIONS = [
    dict(axis='AX-Q1', description='reproduce the live defect verbatim -- drop the claim_abstain conjunct',
         file=HERMES_REPORT, search=_OUTER_GUARD,
         replace='if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" ]]; then',
         tests=[Q1]),
    dict(axis='AX-Q2', description='drop the legacy_rows_present conjunct',
         file=HERMES_REPORT, search=_ABSTAIN_IF,
         replace=('if [[ "${sid_legacy_suppressed}" == "true" && '
                  '"${event_rows_present}" == "false" && '
                  '"${owner_record_absent}" == "true" ]]; then'),
         tests=[Q2]),
    dict(axis='AX-Q3', description='drop the event_rows_present conjunct',
         file=HERMES_REPORT, search=_ABSTAIN_IF,
         replace=('if [[ "${sid_legacy_suppressed}" == "true" && '
                  '"${legacy_rows_present}" == "false" && '
                  '"${owner_record_absent}" == "true" ]]; then'),
         tests=[Q3]),
    dict(axis='AX-Q4', description=(
             'drop BOTH ledger-presence conjuncts (narrower than the plan\'s shared '
             '`if true; then` -- see module docstring deviation note): forces '
             'abstention for a dual-ledger session regardless of either ledger\'s '
             'content, without forcing it for every unsuppressed session too'),
         file=HERMES_REPORT, search=_ABSTAIN_IF,
         replace=('if [[ "${sid_legacy_suppressed}" == "true" && '
                  '"${owner_record_absent}" == "true" ]]; then'),
         tests=[Q4]),
    dict(axis='AX-Q5', description=(
             'drop ONLY the suppression conjunct (narrower than the plan\'s shared '
             '`if true; then` -- see module docstring deviation note): forces '
             'abstention for an unsuppressed fresh session without touching a '
             'suppressed dual-ledger one'),
         file=HERMES_REPORT, search=_ABSTAIN_IF,
         replace=('if [[ "${legacy_rows_present}" == "false" && '
                  '"${event_rows_present}" == "false" && '
                  '"${owner_record_absent}" == "true" ]]; then'),
         tests=[Q5], non_overlap_test=Q4),
    dict(axis='AX-Q6', description='swap the per-session local for the fleet-global boolean',
         file=HERMES_REPORT, search=_ABSTAIN_IF,
         replace=('if [[ "${LEGACY_COMPLETIONS_SKIP}" == "true" && '
                  '"${legacy_rows_present}" == "false" && '
                  '"${event_rows_present}" == "false" && '
                  '"${owner_record_absent}" == "true" ]]; then'),
         tests=[Q6]),
    dict(axis='AX-Q7', description='reproduce the live defect on the settle-gate-delayed tick -- drop the claim_abstain conjunct',
         file=HERMES_REPORT, search=_OUTER_GUARD,
         replace='if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" ]]; then',
         tests=[Q7], non_overlap_test=Q5),
    dict(axis='AX-Q8', description='publish a legacy record from the abstain branch (reintroduces a durable wrong claim)',
         file=HERMES_REPORT, search=_ABSTAIN_SET,
         replace=(_ABSTAIN_SET +
                  '\n      _claim_session_owner "${sid}" "legacy" "0" >/dev/null 2>&1 || true'),
         tests=[Q8]),
    dict(axis='AX-Q9', description='invert the outer guard so the claim block is reachable only on the abstain path',
         file=HERMES_REPORT, search=_OUTER_GUARD,
         replace=('if [[ "${OWNERSHIP_PROTOCOL_ACTIVE}" == "true" && '
                  '"${claim_abstain}" == "true" ]]; then'),
         tests=[Q9]),
    dict(axis='AX-Q10', description="disable the owners pass's live-set insertion (every record looks absent from state.db)",
         file=PRUNE_MARKERS, search=_LIVE_SET_INSERT,
         replace='pass  # AX-Q10 mutation: live-set insertion disabled',
         tests=[Q10]),
    dict(axis='AX-Q11', description='publish a legacy record from the abstain branch (order-1 leg -- legacy must publish nothing before the event path claims)',
         file=HERMES_REPORT, search=_ABSTAIN_SET,
         replace=(_ABSTAIN_SET +
                  '\n      _claim_session_owner "${sid}" "legacy" "0" >/dev/null 2>&1 || true'),
         tests=[Q11], non_overlap_test=Q5),
    dict(axis='AX-Q13', description='force the engagement gate always active on a disengaged install',
         file=HERMES_REPORT, search=_ENGAGEMENT_DEFAULT, replace='OWNERSHIP_PROTOCOL_ACTIVE="true"',
         tests=[Q13A], note=(
             'Targets test_q13a only. Empirically verified: this mutation does NOT '
             'break test_q13b (disengaged AND suppressed), because claim_abstain\'s '
             'own predicate independently protects that leg -- sid_legacy_suppressed '
             'is computed regardless of OWNERSHIP_PROTOCOL_ACTIVE, so a suppressed '
             'session with no ledger rows and no owner record still abstains even '
             'when the engagement gate is forced active. This is a genuine '
             'defense-in-depth property of the fix, not a coverage gap -- q13b is '
             'reported as PASS-either-way rather than folded into a row that would '
             'misrepresent it as mutation-covered.')),
    dict(axis='AX-Q14', description="swap the emission guard's variable for the fleet-global boolean",
         file=HERMES_REPORT, search=_EMISSION_GUARD,
         replace=('if [[ "${LEGACY_COMPLETIONS_SKIP}" != "true" && '
                  '"${session_event_owned}" != "true" ]]; then'),
         tests=[Q14]),
    dict(axis='AX-Q16', description='drop the EVENT_PATH_LIVE conjunct so the per-tick aggregate is always info',
         file=HERMES_REPORT, search=_ABSTAIN_REPORT, replace='if true; then',
         tests=[Q16], note=(
             'This row covers AX-Q16\'s WARN half only. The axis\'s retention half '
             '(spool ageing past REVENIUM_MARKER_RETENTION_DAYS) characterises '
             'pre-existing prune_spool_dir behaviour this diff does not change (E-14) '
             'and would pass with the abstention removed entirely -- it is not '
             'mutation-covered by this or any row, by design; see PLAN.md\'s own '
             'axis-register note for AX-Q16.')),
    dict(axis='AX-Q17', description=(
             "gate BOTH jobs-create call sites (the WR-02 precheck stage AND the "
             "main in-loop stage) on sid_legacy_suppressed -- modelling a future "
             "refactor's \"why create a job for a session we do not own\" reasoning, "
             "applied consistently to every jobs-create call site"),
         file=HERMES_REPORT,
         edits=[
             (_PRECHECK_JOBS_IF,
              _PRECHECK_JOBS_IF.replace(
                  '"${JOBS_CLI_CAPABLE}" == "true" && ',
                  '"${JOBS_CLI_CAPABLE}" == "true" && "${sid_legacy_suppressed}" != "true" && ')),
             (_MAIN_JOBS_IF,
              _MAIN_JOBS_IF.replace(
                  '"${JOBS_CLI_CAPABLE}" == "true" && ',
                  '"${JOBS_CLI_CAPABLE}" == "true" && "${sid_legacy_suppressed}" != "true" && ')),
         ],
         tests=[Q17], note=(
             'DEVIATION FROM PLAN.md, RECORDED HERE AND IN THE SUMMARY: the plan '
             'specified this row as `_ABSTAIN_SET` -> append an early `continue` on '
             'the abstain path. Empirically verified before writing this row: that '
             'exact mutation is NOT caught, because hermes-report.sh has a SECOND, '
             'EARLIER job-creation call site -- the WR-02 precheck stage '
             '(quick-260814-e7c), which runs BEFORE any ownership/abstention code '
             'and is deliberately designed to be robust to a downstream `continue` '
             '(its own comment: "Runs BEFORE the token pre-filter guards so that '
             'token-stable sessions ... still reach the jobs-create stage"). A '
             '`continue` placed in the abstain branch (this task\'s own new code, '
             'positioned per PLAN.md\'s own placement instruction, immediately after '
             'legacy_rows_present) therefore cannot possibly intercept a job the '
             'precheck stage already created earlier in the SAME loop iteration. '
             'This mutation instead targets BOTH real call sites directly, modelling '
             'the axis\'s own feared reasoning applied where it would actually bite. '
             'The asymmetry PLAN.md asked this row to demonstrate still holds: this '
             'mutation leaves every billing axis green, including AX-Q1 (an '
             'unclaimed session is still billed correctly by the event path on its '
             'own tick) -- AX-Q17 is still the only row that catches it.')),
]

STRUCTURAL_AXES = [
    dict(axis='AX-Q12', note=(
        "Argued structurally per PLAN.md, and given a construction-based in-tree proof "
        "(test_q12), not a fabricated mutation: the new abstention code reads exactly "
        "three fixed, profile-scoped artifacts -- LEDGER_FILE, EVENT_LEDGER_FILE, "
        "DRAIN_STATUS_FILE -- each derived from HERMES_HOME/REVENIUM_STATE_DIR, with "
        "no glob, sweep, or wildcard anywhere in the new code. There is no "
        "cross-profile surface in the abstention predicate to widen, mirroring the "
        "AX-13 precedent in tests/mutation_verify_takeover.py.")),
    dict(axis='AX-Q15', note=(
        "Characterisation, not a fix: a `legacy` owner record with no second line and "
        "zero rows on either billing ledger can only have been written by the PRE-FIX "
        "defect this quick task closes -- a migration state, not a steady state this "
        "diff produces. test_q15 asserts both paths stay off such a record exactly as "
        "found; the operator remedy (delete owners/<sid> while the event path is live) "
        "is documented in docs/event-metering.md, not implemented as a code path -- "
        "inferring claimability from a defective record's shape would be option (iii), "
        "rejected in PLAN.md's <chosen_shape>. No mutation is constructed because there "
        "is no NEW code guarding this state to mutate; the existing resolution "
        "(claim_owner == 'legacy' blocks legacy re-emission, api-event-report.sh defers "
        "to any non-'event' owner) is entirely PRE-EXISTING and already covered by "
        "test_session_ownership_record.py's own suite.")),
]


def print_table(rows):
    # Deliberately NOT delegating to mutation_verify_takeover.print_table:
    # that function's footer prints ITS OWN module-level STRUCTURAL_AXES
    # (AX-20, AX-13 -- the mode-aware takeover's axes), which would be
    # printed under a report about the abstention's axes and misattributed.
    # The row-printing shape is reused by hand; the footer prints THIS
    # module's own STRUCTURAL_AXES (AX-Q12, AX-Q15) and per-row notes.
    print()
    print('=' * 100)
    print('PER-AXIS MUTATION VERIFICATION RESULTS (quick-260818-jbl)')
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
    for row in MUTATIONS:
        if row.get('note'):
            print(f'{row["axis"]} note:')
            print(f'  {row["note"]}')
            print()
    for note in STRUCTURAL_AXES:
        print(f'{note["axis"]} (structural, no mutation):')
        print(f'  {note["note"]}')
        print()
    print('=' * 100)


def run_one_mutation_row(row, backups):
    axis = row['axis']
    target = row['file']
    tests = row['tests']

    # Most rows are a single (search, replace) pair. AX-Q17 needs TWO
    # coordinated edits to the SAME file (see its own description) --
    # `edits` is a list of (search, replace) pairs applied in sequence;
    # `restore_from_backup` below restores the whole file from its pristine
    # bytes regardless of how many edits were applied, so no special
    # restore logic is needed for the multi-edit case.
    edits = row.get('edits') or [(row['search'], row['replace'])]
    for search, replace in edits:
        apply_mutation(target, search, replace)
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

    post = run_targeted_tests(tests)
    if 'hard_error' in post or post['verdict'] != 'OK':
        raise MutationVerifyError(
            f'[{axis}] restore verification FAILED -- targeted tests do not pass '
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


def main():
    backups = load_pristine_backups(TARGET_FILES)

    results = []
    aborted = False
    for row in MUTATIONS:
        try:
            results.append(run_one_mutation_row(row, backups))
        except MutationVerifyError as exc:
            for f in TARGET_FILES:
                restore_from_backup(f, backups)
            print(f'\nHARD ERROR on axis {row["axis"]}: {exc}\n', file=sys.stderr)
            aborted = True
            break

    print_table(results)

    if aborted:
        print('ABORTED -- see hard error above. Exiting non-zero.', file=sys.stderr)
        sys.exit(1)

    any_row_failed = any(not r['pass'] for r in results)

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
    from tests.mutation_verify_takeover import _RAN_RE, _TRAILING_OK_RE
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
