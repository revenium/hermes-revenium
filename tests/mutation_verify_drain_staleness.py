#!/usr/bin/env python3
"""quick-260818-f1g -- per-axis mutation verification for drain-status.sh's
staleness route and hermes-report.sh's per-session legacyRetainedSids
carve-out.

Committed, stdlib-only, operator-invoked tool. NOT a `test_*.py` module --
the filename deliberately does not match the discovery pattern, so it never
runs as part of `python3 -m unittest discover`. Run it directly:

    python3 tests/mutation_verify_drain_staleness.py

Modeled on `tests/mutation_verify_takeover.py` and preserving its whole
runner contract verbatim (search-count-exactly-one, digest-before/after,
pristine-backup restore + re-verification, NO_COLOR=1, the ANSI-stripped
trailing-status-line regexes, and "Ran N tests" as a hard error at N=0):

  - The mutation search substring must occur EXACTLY once in the target
    file before it is applied. Zero or more than one is a hard error.
  - The file's digest is checked before and after the write.
  - The verdict is read from unittest's OWN trailing status line ("OK" or
    "OK (expected failures=1)" or "FAILED (...)"), never by counting
    matched lines. `_TRAILING_OK_RE` is reused VERBATIM from
    mutation_verify_takeover.py -- a bare `^OK$` anchor silently reports a
    passing suite as FAILED once the suite contains any decorated test,
    and this repo's own history records that exact bug shipping once
    already.
  - Each targeted test ID must appear among unittest's own FAIL:/ERROR:
    failure headers.
  - A collection error, an import error, or a run reporting zero tests is
    a HARD ERROR, never a pass.
  - Every mutation is restored from a PRISTINE, in-memory backup taken once
    at the very start. After restoring, the SAME targeted tests are
    re-run and required to PASS before the next row runs.
  - `NO_COLOR=1` is forced into the subprocess environment.

ONE extension beyond mutation_verify_takeover.py's contract: AX-S25's row
carries a `cross_check_tests` list (AX-S07, AX-S11) that must stay GREEN
while its mutation is applied. AX-S07 and AX-S11 pin DETECTION (is the
session judged stale, is the corruption counted); AX-S25 pins CONSEQUENCE
(what a stale verdict is allowed to switch off). A mutation that removes
the carve-out but leaves AX-S07/AX-S11 green is proof the row hit
consequence, not detection -- reported as its own line in the table.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAIN_STATUS = ROOT / 'skills' / 'revenium' / 'scripts' / 'drain-status.sh'
HERMES_REPORT = ROOT / 'skills' / 'revenium' / 'scripts' / 'hermes-report.sh'
TARGET_FILES = [DRAIN_STATUS, HERMES_REPORT]

MOD = 'tests.test_drain_staleness'
THRESHOLD = f'{MOD}.ThresholdBoundaryTests'
RESUME = f'{MOD}.ResumeAndActivityCompositionTests'
ACTIVITY_EDGE = f'{MOD}.ActivityTermEdgeShapeTests'
CORRUPTION = f'{MOD}.LedgerCorruptionAndUnreadableSourceTests'
PRECEDENCE = f'{MOD}.PrecedenceAndUnchangedBranchTests'
TUNABLE = f'{MOD}.TunableAndDocumentShapeTests'
CONSUMER_E2E = f'{MOD}.ConsumerEndToEndTests'
CONSUMER_CARVEOUT = f'{MOD}.ConsumerCarveOutInterpretationTests'
TAKEOVER = f'{MOD}.TakeoverPerSessionSuppressionTests'

AX_S01 = f'{THRESHOLD}.test_ax_s01_age_just_inside_threshold_blocks'
AX_S02 = f'{THRESHOLD}.test_ax_s02_age_just_outside_threshold_drains'
AX_S03 = f'{THRESHOLD}.test_ax_s03_age_exactly_at_threshold_is_stale'
AX_S04 = f'{RESUME}.test_ax_s04_resume_via_activity_withdraws_drained_verdict'
AX_S05 = f'{RESUME}.test_ax_s05_resume_via_ledger_line_withdraws_drained_verdict'
AX_S06 = f'{RESUME}.test_ax_s06_recent_activity_blocks_despite_ancient_ledger'
AX_S07 = f'{ACTIVITY_EDGE}.test_ax_s07_null_activity_falls_back_to_ledger_counted_and_retained'
AX_S08 = f'{ACTIVITY_EDGE}.test_ax_s08_missing_activity_column_does_not_break_the_gate'
AX_S09 = f'{ACTIVITY_EDGE}.test_ax_s09_unparseable_activity_refuses_staleness_for_that_session'
AX_S10 = f'{ACTIVITY_EDGE}.test_ax_s10_future_dated_timestamp_is_never_stale'
AX_S11 = f'{CORRUPTION}.test_ax_s11_unparsed_ledger_lines_are_counted_not_silent'
AX_S12 = f'{CORRUPTION}.test_ax_s12_unreadable_ledger_still_exits_1_and_staleness_unreachable'
AX_S13 = f'{CORRUPTION}.test_ax_s13_unreadable_state_db_still_exits_1_and_staleness_unreachable'
AX_S26 = f'{CORRUPTION}.test_ax_s26_unparseable_ts_on_an_attributable_line_refuses_staleness_for_that_sid'
AX_S27 = f'{CORRUPTION}.test_ax_s27_unattributable_corruption_retains_every_stale_session_without_closing_the_gate'
AX_S14 = f'{PRECEDENCE}.test_ax_s14_stale_but_recently_ended_still_blocked_by_settle_window'
AX_S15 = f'{PRECEDENCE}.test_ax_s15_ended_past_settle_branch_verdict_unchanged'
AX_S16 = f'{PRECEDENCE}.test_ax_s16_absent_from_state_db_branch_verdict_unchanged'
AX_S17 = f'{PRECEDENCE}.test_ax_s17_open_session_absent_from_ledger_is_not_tracked'
AX_S18 = f'{PRECEDENCE}.test_ax_s18_stale_session_still_requires_quiet_ticks'
AX_S19 = f'{TUNABLE}.test_ax_s19_configured_threshold_is_floored_above_the_settle_window'
AX_S20 = f'{TUNABLE}.test_ax_s20_zero_threshold_restores_pre_change_behaviour'
AX_S21 = f'{TUNABLE}.test_ax_s21_two_profiles_have_independent_stale_verdicts'
AX_S22 = f'{TUNABLE}.test_ax_s22_pending_cap_still_caps_at_50_and_carries_stale_key'
AX_S23 = f'{TUNABLE}.test_ax_s23_status_document_keeps_every_preexisting_key'
AX_S24 = f'{CONSUMER_E2E}.test_ax_s24_hermes_report_honours_then_refuses_a_staleness_verdict'
AX_S25 = f'{CONSUMER_CARVEOUT}.test_ax_s25_ledger_only_stale_session_is_retained_while_the_gate_reports_drained'
AX_S28 = f'{CONSUMER_CARVEOUT}.test_ax_s28_absent_retained_list_reproduces_todays_global_suppression'
AX_S29 = f'{CONSUMER_CARVEOUT}.test_ax_s29_a_session_not_on_the_retained_list_is_still_suppressed'
AX_S30 = f'{TAKEOVER}.test_ax_s30_takeover_branch_uses_the_per_session_suppression_not_the_global_boolean'

# ---------------------------------------------------------------------------
# Search/replace fragments, extracted verbatim from the shipped source so a
# search-string typo cannot silently match zero times (caught by
# apply_mutation's exact-count-1 assertion regardless, but kept as named
# constants for readability, mirroring mutation_verify_takeover.py's style).
# ---------------------------------------------------------------------------

_STALE_CMP = '(now - last_seen) >= stale_seconds_effective'
_ACTIVITY_UPDATE = 'if activity_ts > last_seen:\n                            last_seen = activity_ts'
_RETENTION_ADD = (
    'if not has_activity_signal:\n'
    '                        stale_without_activity_signal += 1\n'
    '                        stale_granted_no_activity_sids.add(sid)'
)
_ACTIVITY_EXCEPT = (
    '                    except (TypeError, ValueError):\n'
    '                        refused = True'
)
_UNATTRIBUTABLE_COUNT = (
    '                if parsed is None:\n'
    '                    ledger_unparsed_lines += 1\n'
    '                    continue'
)
_LEDGER_UNREADABLE_FINISH = (
    "_finish(False, False, 0, 0, 0, [], {}, {},\n"
    "                reason='legacy ledger unreadable')"
)
_OPEN_SIDS_EXCEPT = (
    "        except Exception:\n"
    "            # A db that exists but cannot be queried leaves openness\n"
    "            # indeterminate for every session. Never assume drained on doubt.\n"
    "            pending_preview = sorted(sid_max_ts.items(), key=lambda kv: kv[1])[:pending_cap]\n"
    "            _finish(False, False, len(sid_max_ts), 0, len(sid_max_ts),\n"
    "                    [{'sid': sid, 'ageSeconds': round(now - ts, 1)}\n"
    "                     for sid, ts in pending_preview],\n"
    "                    {}, {}, reason='state.db unreadable')"
)
_ABSENT_BRANCH_TERMINAL = '            terminal = True\n        else:'
_TRACKED_DICT = (
    '    tracked = {\n'
    '        sid: ts for sid, ts in sid_max_ts.items()\n'
    '        if (now - ts) < retention_cutoff_seconds or sid in open_sids\n'
    '    }'
)
_IS_DRAINED = 'is_drained = terminal and new_count >= quiet_ticks_required'
_FLOOR_LINE = 'stale_seconds_effective = max(stale_seconds_configured, settle_seconds + 86400.0)'
_OPT_OUT_IF = 'if stale_seconds_configured <= 0:'
_PENDING_CAPPED = 'pending_capped = pending[:pending_cap]'
_SETTLE_TERMINAL = 'terminal = (now - float(ended_at)) >= settle_seconds'
_ROUTE1A_RETURN = 'return sid, None'
_WIDEN_IF = (
    'if ledger_unparsed_lines > 0:\n'
    '        legacy_retained_sids = sorted(stale_granted_sids)\n'
    '    else:'
)
_COLUMN_ABSENT_SELECT = "'SELECT id FROM sessions WHERE ended_at IS NULL'"
_LAST_SEEN_INIT = 'last_seen = max_ts'
_DOC_TAIL = "        'drained': drained,\n        'determined': determined,\n    }"

_HR_EMISSION_GUARD = (
    'if [[ "${sid_legacy_suppressed}" != "true" && '
    '"${session_event_owned}" != "true" ]]; then'
)
_HR_TAKEOVER_GUARD = (
    'if [[ "${EVENT_PATH_LIVE}" == "true" || '
    '"${sid_legacy_suppressed}" == "true" ]]; then'
)
_HR_CASE_BLOCK = (
    'local sid_legacy_retained="false"\n'
    '    case "${LEGACY_RETAINED_SIDS}" in\n'
    '      *$\'\\n\'"${sid}"$\'\\n\'*) sid_legacy_retained="true" ;;\n'
    '    esac'
)
_HR_CASE_BLOCK_INVERTED = (
    'local sid_legacy_retained="false"\n'
    '    case "${LEGACY_RETAINED_SIDS}" in\n'
    '      *$\'\\n\'"${sid}"$\'\\n\'*) sid_legacy_retained="false" ;;\n'
    '      *) sid_legacy_retained="true" ;;\n'
    '    esac'
)
_HR_GATE_DRAINED_IF = 'if [[ "${DRAIN_GATE_DRAINED}" == "true" ]]; then'

MUTATIONS = [
    dict(axis='AX-S01', description='bias the observed age up by 1000s (a not-yet-stale session looks stale)',
         file=DRAIN_STATUS, search=_STALE_CMP,
         replace='(now - last_seen) + 1000 >= stale_seconds_effective',
         tests=[AX_S01]),
    dict(axis='AX-S02', description='the staleness comparison never trips',
         file=DRAIN_STATUS, search=_STALE_CMP, replace='False',
         tests=[AX_S02]),
    dict(axis='AX-S03', description='weaken `>=` to `>` at the threshold boundary',
         file=DRAIN_STATUS, search=_STALE_CMP,
         replace='(now - last_seen) > stale_seconds_effective',
         tests=[AX_S03]),
    dict(axis='AX-S04', description='the activity update becomes a no-op re-assignment',
         file=DRAIN_STATUS, search=_ACTIVITY_UPDATE,
         replace='if activity_ts > last_seen:\n                            last_seen = last_seen',
         tests=[AX_S04]),
    dict(axis='AX-S05', description="the ledger parser keeps the OLDEST line's ts instead of the newest",
         file=DRAIN_STATUS, search='ts > sid_max_ts[sid]', replace='ts < sid_max_ts[sid]',
         tests=[AX_S05]),
    dict(axis='AX-S06', description='invert the activity-vs-ledger max() direction',
         file=DRAIN_STATUS, search='if activity_ts > last_seen:',
         replace='if activity_ts < last_seen:',
         tests=[AX_S06]),
    dict(axis='AX-S07', description='a NULL-activity session is never added to the no-activity retained set',
         file=DRAIN_STATUS, search=_RETENTION_ADD,
         replace=_RETENTION_ADD.replace('if not has_activity_signal:', 'if False:'),
         tests=[AX_S07]),
    dict(axis='AX-S08', description='the column-absent branch selects the (nonexistent) activity column anyway',
         file=DRAIN_STATUS, search=_COLUMN_ABSENT_SELECT,
         replace="'SELECT id, last_activity_at FROM sessions WHERE ended_at IS NULL'",
         tests=[AX_S08]),
    dict(axis='AX-S09', description='an unparseable activity value is silently ignored instead of refusing staleness',
         file=DRAIN_STATUS, search=_ACTIVITY_EXCEPT,
         replace=_ACTIVITY_EXCEPT.replace('refused = True', 'pass'),
         tests=[AX_S09]),
    dict(axis='AX-S10', description='clamp a negative age to its absolute value (a future timestamp looks equally stale)',
         file=DRAIN_STATUS, search=_STALE_CMP,
         replace='abs(now - last_seen) >= stale_seconds_effective',
         tests=[AX_S10]),
    dict(axis='AX-S11', description='an unattributable malformed line is no longer counted',
         file=DRAIN_STATUS, search=_UNATTRIBUTABLE_COUNT,
         replace='                if parsed is None:\n                    continue',
         tests=[AX_S11]),
    dict(axis='AX-S12', description='an unreadable ledger is silently treated as an empty one',
         file=DRAIN_STATUS, search=_LEDGER_UNREADABLE_FINISH, replace='sid_max_ts = {}',
         tests=[AX_S12]),
    dict(axis='AX-S13', description='an unreadable state.db (open_sids query) is silently swallowed',
         file=DRAIN_STATUS, search=_OPEN_SIDS_EXCEPT, replace='        except Exception:\n            pass',
         tests=[AX_S13]),
    dict(axis='AX-S14', description='staleness leaks into the ended-past-settle branch',
         file=DRAIN_STATUS, search=_SETTLE_TERMINAL,
         replace=_SETTLE_TERMINAL + ' or (now - max_ts) >= stale_seconds_effective',
         tests=[AX_S14]),
    dict(axis='AX-S15', description='invert the settle-window comparison on the ended branch',
         file=DRAIN_STATUS, search=_SETTLE_TERMINAL,
         replace='terminal = (now - float(ended_at)) <= settle_seconds',
         tests=[AX_S15]),
    dict(axis='AX-S16', description='the absent-from-state.db branch stops granting terminal',
         file=DRAIN_STATUS, search=_ABSENT_BRANCH_TERMINAL,
         replace='            terminal = False\n        else:',
         tests=[AX_S16]),
    dict(axis='AX-S17', description='open_sids sessions are unioned directly into tracked, bypassing the ledger keying',
         file=DRAIN_STATUS, search=_TRACKED_DICT,
         replace=_TRACKED_DICT + '\n    for _os in open_sids:\n        if _os not in tracked:\n            tracked[_os] = now',
         tests=[AX_S17]),
    dict(axis='AX-S18', description='drop the quiet-tick requirement from is_drained',
         file=DRAIN_STATUS, search=_IS_DRAINED, replace='is_drained = terminal',
         tests=[AX_S18]),
    dict(axis='AX-S19', description='drop the settle-window floor entirely',
         file=DRAIN_STATUS, search=_FLOOR_LINE,
         replace='stale_seconds_effective = stale_seconds_configured',
         tests=[AX_S19]),
    dict(axis='AX-S20', description='the <= 0 opt-out never triggers',
         file=DRAIN_STATUS, search=_OPT_OUT_IF, replace='if False:',
         tests=[AX_S20]),
    dict(axis='AX-S21', description='last_seen is hoisted to the max across every tracked sid, not just the current one',
         file=DRAIN_STATUS, search=_LAST_SEEN_INIT, replace='last_seen = max(tracked.values())',
         tests=[AX_S21]),
    dict(axis='AX-S22', description='PENDING_CAP effectively stops capping the pending list',
         file=DRAIN_STATUS, search=_PENDING_CAPPED,
         replace='pending_capped = pending[:pending_cap + 1000]',
         tests=[AX_S22]),
    dict(axis='AX-S23', description='drop the determined key from the status document',
         file=DRAIN_STATUS, search=_DOC_TAIL,
         replace="        'drained': drained,\n    }",
         tests=[AX_S23]),
    dict(axis='AX-S24', description='the startup gate resolution ignores the drain gate\'s actual verdict once disabled',
         file=HERMES_REPORT, search=_HR_GATE_DRAINED_IF, replace='if true; then',
         tests=[AX_S24]),
    dict(axis='AX-S25', description='membership test at the emission guard ignores the retained set (the fleet-global boolean restored)',
         file=HERMES_REPORT, search=_HR_EMISSION_GUARD,
         replace='if [[ "${LEGACY_COMPLETIONS_SKIP}" != "true" && "${session_event_owned}" != "true" ]]; then',
         tests=[AX_S25], cross_check_tests=[AX_S07, AX_S11]),
    dict(axis='AX-S26', description='attributable route-1a corruption is treated as unattributable (loses its sid)',
         file=DRAIN_STATUS, search=_ROUTE1A_RETURN, replace='return None',
         tests=[AX_S26]),
    dict(axis='AX-S27', description='unattributable corruption never widens the retained carve-out',
         file=DRAIN_STATUS, search=_WIDEN_IF,
         replace=_WIDEN_IF.replace('if ledger_unparsed_lines > 0:', 'if False:'),
         tests=[AX_S27]),
    dict(axis='AX-S28', description="the startup read resolves a MISSING legacyRetainedSids key to the all-sids set instead of the empty set",
         file=HERMES_REPORT, search=_HR_CASE_BLOCK, replace=_HR_CASE_BLOCK_INVERTED,
         tests=[AX_S28]),
    dict(axis='AX-S29', description="a session absent from a well-formed, non-empty legacyRetainedSids list is retained anyway ('retain unless proven drained')",
         file=HERMES_REPORT, search=_HR_CASE_BLOCK, replace=_HR_CASE_BLOCK_INVERTED,
         tests=[AX_S29]),
    dict(axis='AX-S30', description='the takeover predicate reverts to the fleet-global LEGACY_COMPLETIONS_SKIP boolean',
         file=HERMES_REPORT, search=_HR_TAKEOVER_GUARD,
         replace='if [[ "${EVENT_PATH_LIVE}" == "true" || "${LEGACY_COMPLETIONS_SKIP}" == "true" ]]; then',
         tests=[AX_S30]),
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
            f'search substring occurs {count} time(s) in {target} (must be EXACTLY 1) -- '
            f'a mutation that cannot be applied unambiguously produces a green result '
            f'that looks like proof, not proof.\nsearch={search!r}')
    before_digest = sha256_of(target)
    new_text = text.replace(search, replace, 1)
    target.write_text(new_text)
    after_digest = sha256_of(target)
    if after_digest == before_digest:
        raise MutationVerifyError(
            f'{target} digest did not change after the mutation was applied -- the write '
            f'silently no-op\'d')


_RAN_RE = re.compile(r'^Ran (\d+) tests? in', re.MULTILINE)
# Reused VERBATIM from mutation_verify_takeover.py (see that file's own
# comment): unittest's success line is NOT always a bare 'OK' -- it becomes
# 'OK (expected failures=1)' as soon as the suite contains a decorated test,
# and this host's ambient FORCE_COLOR wraps it in ANSI codes besides. A
# '^OK$' anchor silently reports a passing suite as FAILED.
_TRAILING_OK_RE = re.compile(r'^OK(?: \([^)]*\))?$', re.MULTILINE)
_TRAILING_FAILED_RE = re.compile(r'^FAILED \(([^)]*)\)$', re.MULTILINE)
_FAIL_HEADER_RE = re.compile(r'^(?:FAIL|ERROR): \S+ \(([\w.]+)\)\s*$', re.MULTILINE)


def run_targeted_tests(test_ids, timeout=180):
    """Run exactly the given fully-qualified test IDs via `python3 -m
    unittest`, capturing combined stdout+stderr verbatim. NO_COLOR=1 is
    forced (see module docstring)."""
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
            f'{test_ids} -- this is a HARD ERROR (import/collection failure), never a '
            f'pass or a caught mutation.\n--- combined output ---\n{combined}')}

    if _TRAILING_OK_RE.search(combined):
        verdict_status = 'OK'
    else:
        failed_match = _TRAILING_FAILED_RE.search(combined)
        if failed_match is None:
            return {'hard_error': (
                f'could not find unittest\'s own trailing "OK" or "FAILED (...)" status '
                f'line for {test_ids} -- treating as a hard error rather than guessing.\n'
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
    cross_check_tests = row.get('cross_check_tests') or []

    apply_mutation(target, row['search'], row['replace'])
    try:
        result = run_targeted_tests(tests)
        if 'hard_error' in result:
            raise MutationVerifyError(f'[{axis}] {result["hard_error"]}')

        targeted_present = all(t in result['failed_ids'] for t in tests)
        row_pass = (result['verdict'] == 'FAILED') and targeted_present

        cross_check_pass = None
        if cross_check_tests:
            cc_result = run_targeted_tests(cross_check_tests)
            if 'hard_error' in cc_result:
                raise MutationVerifyError(
                    f'[{axis}] hard error checking cross-check tests '
                    f'{cross_check_tests}: {cc_result["hard_error"]}')
            cross_check_pass = cc_result['verdict'] == 'OK'
            row_pass = row_pass and cross_check_pass
    finally:
        restore_from_backup(target, backups)

    # Restore-verification: the SAME targeted tests (plus any cross-check
    # tests) must pass against the now-restored tree, or a broken restore
    # silently poisons every axis that runs after this one.
    post = run_targeted_tests(tests + cross_check_tests)
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
        'cross_check_tests': cross_check_tests,
        'cross_check_pass': cross_check_pass,
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
        if r['cross_check_tests']:
            print(f'Cross-check (must stay GREEN): {", ".join(r["cross_check_tests"])} '
                  f'-> {"PASS" if r["cross_check_pass"] else "FAIL"}')
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
