"""Phase 42 Plan 01 — the correction ledger prefix, proven unmatchable first.

`41-ARCHITECTURE.md` names this in as many words: "phase 42 should treat 'the
prefix really is unmatchable' as its own first test, not an assumption
inherited from this document." `42-CONTEXT.md`'s `<specifics>` repeats it
verbatim. This module is that test, written and passing BEFORE any
correction-authoring code exists.

Requirements covered:
  EGV-09 — corrections append; the original assessment and its complete
           history are preserved, never destructively replaced. This module
           proves the mechanism that makes that safe: a `JOB:<id>:correction:
           <seq>:<ts>` ledger line can neither forge an "already reported"
           verdict (OUTCOME-01) nor a "create confirmed" verdict (OUTCOME-04)
           against the ordinary per-tick `job_outcome_queue` path.

Decision defended:
  D-01 (42-CONTEXT.md) — Phase 42 builds the full C-06 correction path with
  its own distinct ledger prefix, deliberately disjoint from the two grep
  gates `hermes-report.sh`'s post-loop outcome stage already relies on for
  idempotency. This module is the proof that disjointness holds against a
  real ledger file, through the real `grep` engine the production gate uses
  -- not `re.match`, and not an assumption carried over from `41-ARCHITECTURE.md`.

Every test in this module runs OFFLINE: no network, no revenium CLI, no
subprocess other than a real `grep` invocation against a real temp file.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
SCRIPTS_DIR = SKILL / 'scripts'

HERMES_REPORT_SH = SCRIPTS_DIR / 'hermes-report.sh'

# The exact gate-comment anchors in hermes-report.sh's post-loop outcome
# stage, copied verbatim from the live source (not retyped from the plan).
OUTCOME_01_GATE_COMMENT = '# OUTCOME-01 gate:'
OUTCOME_04_GATE_COMMENT = '# OUTCOME-04 gate:'


def _extract_grep_pattern(script_text, gate_comment, job_id):
    """Pull the grep -q pattern immediately following `gate_comment`.

    Reads the LIVE hermes-report.sh source rather than hardcoding the
    pattern from the plan -- if the gate has moved or been reworded, this
    returns None and the caller must fail loudly (a silently-skipped
    extraction would turn this proof into a no-op, per Task 1's own
    instruction).
    """
    idx = script_text.find(gate_comment)
    if idx == -1:
        return None
    window = script_text[idx:idx + 400]
    match = re.search(r'grep -q "([^"]+)"', window)
    if not match:
        return None
    return match.group(1).replace('${outcome_id}', job_id)


def _grep_matching_lines(pattern, ledger_path):
    """Run `pattern` through a REAL grep subprocess against `ledger_path`.

    Deliberately not re.match: the production gate is `grep -q "<pattern>"
    "${JOBS_LEDGER_FILE}"`, and EGV-09/D-01's proof must exercise the same
    matching engine the live code depends on, not a Python re-implementation
    that could silently diverge from grep's own BRE semantics.
    """
    result = subprocess.run(
        ['grep', pattern, str(ledger_path)],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise AssertionError(
            f'EGV-09/D-01: grep exited {result.returncode} unexpectedly for '
            f'pattern {pattern!r} against {ledger_path}: {result.stderr}'
        )
    return [line for line in result.stdout.splitlines() if line]


class LedgerPrefixDisjointnessTests(unittest.TestCase):
    """EGV-09/D-01 -- the correction prefix is unmatchable by construction.

    Proves, against a real jobs-ledger fixture through a real `grep`
    subprocess, that `JOB:<id>:correction:<seq>:<ts>` satisfies neither
    OUTCOME-01 (`^JOB:${outcome_id}:outcome:`) nor OUTCOME-04
    (`^JOB:${outcome_id}:created:`) -- the two grep gates
    `hermes-report.sh`'s post-loop outcome stage relies on for idempotency
    and deferred-create retry.
    """

    JOB_ID = 'assess-42-job-001'
    OTHER_JOB_ID = 'assess-42-job-002'

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.outcome_01_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_01_GATE_COMMENT, self.JOB_ID)
        self.outcome_04_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_04_GATE_COMMENT, self.JOB_ID)
        if self.outcome_01_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-01 gate comment '
                f'{OUTCOME_01_GATE_COMMENT!r} not found (or its grep pattern '
                'not extractable) in hermes-report.sh -- the gate moved and '
                'this proof must be updated, not silently skipped.'
            )
        if self.outcome_04_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-04 gate comment '
                f'{OUTCOME_04_GATE_COMMENT!r} not found (or its grep pattern '
                'not extractable) in hermes-report.sh -- the gate moved and '
                'this proof must be updated, not silently skipped.'
            )

        self.tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-ledger-')
        self.full_ledger = Path(self.tmpdir) / 'revenium-jobs-full.ledger'
        self.full_ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS\n'
            f'JOB:{self.JOB_ID}:correction:1:1755999100\n'
            f'JOB:{self.OTHER_JOB_ID}:created:1755999200\n'
            f'JOB:{self.OTHER_JOB_ID}:outcome:1755999205:SUCCESS\n'
            f'JOB:{self.OTHER_JOB_ID}:correction:1:1755999300\n'
        )

        # Deferred-then-corrected shape: a correction filed while the job's
        # outcome was still deferred (no `outcome:` line ever written for
        # this job id). This is the fixture assertion 2 depends on -- the
        # correction line must not be able to forge an "already reported"
        # verdict in the ABSENCE of a real outcome line either.
        self.deferred_then_corrected_ledger = (
            Path(self.tmpdir) / 'revenium-jobs-deferred.ledger'
        )
        self.deferred_then_corrected_ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:correction:1:1755999100\n'
        )

    def test_outcome_01_matches_exactly_the_outcome_line(self):
        matches = _grep_matching_lines(self.outcome_01_pattern, self.full_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-01 must match exactly one line for a job '
            f'id with created+outcome+correction lines, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS',
            'EGV-09/D-01: OUTCOME-01\'s one match must be the outcome line, '
            f'not the correction line -- got {matches[0]!r}'
        )

    def test_outcome_01_does_not_match_deferred_then_corrected_shape(self):
        """A correction filed before any outcome line must not forge OUTCOME-01.

        This is the assertion that a `JOB:<id>:correction:` line cannot make
        the ordinary per-tick outcome stage believe a job was already
        reported when it never was.
        """
        matches = _grep_matching_lines(
            self.outcome_01_pattern, self.deferred_then_corrected_ledger)
        self.assertEqual(
            matches, [],
            'EGV-09/D-01: OUTCOME-01 must match ZERO lines when a ledger '
            'holds only created+correction lines for a job id -- a '
            f'correction line must never forge "already reported", got {matches!r}'
        )

    def test_outcome_04_matches_exactly_the_created_line(self):
        matches = _grep_matching_lines(self.outcome_04_pattern, self.full_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-04 must match exactly one line for a job '
            f'id with created+outcome+correction lines, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:created:1755999000',
            'EGV-09/D-01: OUTCOME-04\'s one match must be the created line, '
            f'not the correction line -- got {matches[0]!r}'
        )

    def test_outcome_04_never_satisfied_by_a_correction_line(self):
        matches = _grep_matching_lines(
            self.outcome_04_pattern, self.deferred_then_corrected_ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: OUTCOME-04 must still match the created line alone '
            f'in the deferred-then-corrected shape, got {matches!r}'
        )
        self.assertEqual(
            matches[0], f'JOB:{self.JOB_ID}:created:1755999000',
            'EGV-09/D-01: a correction line must never satisfy OUTCOME-04 -- '
            f'got {matches[0]!r}'
        )

    def test_correction_prefix_matches_only_its_own_line_job_id_scoped(self):
        """Proves the patterns are job-id-scoped, not merely word-scoped.

        Greps for the correction prefix itself (both job ids share the
        `correction:` word) and asserts it matches exactly the ONE line for
        JOB_ID, never OTHER_JOB_ID's correction line and never either job's
        created/outcome lines.
        """
        correction_pattern = f'^JOB:{self.JOB_ID}:correction:'
        matches = _grep_matching_lines(correction_pattern, self.full_ledger)
        self.assertEqual(
            matches, [f'JOB:{self.JOB_ID}:correction:1:1755999100'],
            'EGV-09/D-01: the correction prefix must match exactly the one '
            f'correction line for this job id, got {matches!r}'
        )


class OrdinaryPathDoubleReportGuardTests(unittest.TestCase):
    """EGV-09/D-01 -- the ordinary path must remain gated.

    This class exists to prevent a future test from drifting into asserting
    that the ordinary `job_outcome_queue` path may report a job id twice
    through `revenium jobs outcome`. Any such assertion IS the regression
    D-01's correction-path design exists to avoid, not a feature to
    preserve -- 42-RESEARCH.md's Pitfall 4 and 42-CONTEXT.md's `<specifics>`
    section both name this exact review warning sign verbatim: "a new test
    asserting a job id can be reported twice through the ordinary
    `job_outcome_queue` path... is the regression this design exists to
    avoid, not a feature."
    """

    JOB_ID = 'assess-42-guard-001'

    def setUp(self):
        self.script_text = HERMES_REPORT_SH.read_text()
        self.outcome_01_pattern = _extract_grep_pattern(
            self.script_text, OUTCOME_01_GATE_COMMENT, self.JOB_ID)
        if self.outcome_01_pattern is None:
            self.fail(
                'EGV-09/D-01: OUTCOME-01 gate comment '
                f'{OUTCOME_01_GATE_COMMENT!r} not found in hermes-report.sh '
                '-- update the extraction anchor before trusting this proof.'
            )
        self.tmpdir = tempfile.mkdtemp(prefix='gsd-phase42-guard-')

    def test_ordinary_path_still_gated_once_outcome_reported(self):
        ledger = Path(self.tmpdir) / 'revenium-jobs.ledger'
        ledger.write_text(
            f'JOB:{self.JOB_ID}:created:1755999000\n'
            f'JOB:{self.JOB_ID}:outcome:1755999005:SUCCESS\n'
        )
        matches = _grep_matching_lines(self.outcome_01_pattern, ledger)
        self.assertEqual(
            len(matches), 1,
            'EGV-09/D-01: the ordinary per-tick path must remain gated by '
            'OUTCOME-01 once a real outcome line exists -- a job id must '
            f'never be reportable twice through job_outcome_queue, got {matches!r}'
        )

    def test_ordinary_path_ungated_before_any_outcome_reported(self):
        """Sanity complement: OUTCOME-01 must NOT block a genuinely-unreported job."""
        ledger = Path(self.tmpdir) / 'revenium-jobs-unreported.ledger'
        ledger.write_text(f'JOB:{self.JOB_ID}:created:1755999000\n')
        matches = _grep_matching_lines(self.outcome_01_pattern, ledger)
        self.assertEqual(
            matches, [],
            'EGV-09/D-01: OUTCOME-01 must not block a job id that has never '
            f'been reported -- got {matches!r}'
        )


if __name__ == '__main__':
    unittest.main()
