"""COMPAT-01 + COMPAT-02 milestone trip-wire for the v1.4 release line.

This file is intentionally minimal. Its job is purely to NAME the
backward-compat acceptance gate for v1.4 so that:

  1. A close-summary or future v1.5+ planner can grep for the single
     identifier `test_v1_4_top_level_wire_is_byte_identical_to_v1_3`
     and get a PASS/FAIL signal for the v1.x top-level wire contract.
  2. Running `python3 -m unittest tests.test_compat_v1_4_meta -v` in
     isolation produces an unambiguous milestone gate result without
     having to know that there are four sibling `tests/test_compat_*.py`
     runners performing the actual byte-level work.

The workhorse runners live in:

  - tests/test_compat_meter_completion.py  (revenium meter completion)
  - tests/test_compat_jobs_create.py       (revenium jobs create)
  - tests/test_compat_jobs_outcome.py      (revenium jobs outcome)
  - tests/test_compat_meter_tool_event.py  (revenium meter tool-event)

Each of those four classes contains exactly one test method that
exercises the relevant Bash script against a synthetic state.db /
markers JSONL / tool-events JSONL via a no-shift `revenium` shim, then
asserts the captured argv against an immutable golden fixture under
tests/fixtures/compat/*.golden.json.

The umbrella below builds a unittest.TestSuite from those four classes
via unittest.defaultTestLoader.loadTestsFromTestCase and asserts the
suite passes. It runs the underlying TestCases a SECOND time per
discover (once via the suite here, once when discover loads them
directly) — that is the point: the umbrella is a milestone-scoped
re-assertion, not a replacement. Net test count delta over Phase 22 is
+1 (the umbrella's single method).

DO NOT regenerate or modify any of the four golden-argv fixtures.
They are the immutable v1.x wire contract. The originating decisions
are Phase 20 D-01..D-04 (golden-argv unit test pattern, reconstruct
from script source, one canonical happy-path golden per verb,
exact_match + pattern_fields allowlist + forbidden_fields denylist).
Phase 23 (this file) is the v1.4 lock-in.
"""
import io
import unittest


class TestV14CompatMeta(unittest.TestCase):
    """Milestone trip-wire for COMPAT-01 + COMPAT-02 on the v1.4 line."""

    def test_v1_4_top_level_wire_is_byte_identical_to_v1_3(self):
        """v1.4 top-level wire MUST match v1.3 byte-for-byte (COMPAT-01, COMPAT-02).

        Gate semantics:
          - COMPAT-01: top-level sessions (no parent_session_id chain)
            ship 100% byte-identical argv to v1.3 across `meter completion`,
            `meter tool-event`, `jobs create`, `jobs outcome`.
          - COMPAT-02: the four v1.3 golden-argv fixtures under
            tests/fixtures/compat/*.golden.json pass without modification.

        Mechanism: build a unittest.TestSuite containing the four existing
        test classes, run it via a TextTestRunner with an in-memory stream,
        and fail loudly with the captured output if any underlying runner
        failed or errored. The failure message includes the verb-specific
        runner output so the reader can immediately see WHICH fixture
        drifted without re-running the suite manually.

        Subagent-aware code paths (Phase 21-22 / v1.4) are explicitly out
        of scope here — those produce DIFFERENT argv via the
        parent_session_id chain walk and are asserted by separate tests
        (e.g. test_hermes_report_subagent_trace_inheritance). Top-level
        argv stays byte-identical.

        Implementation note: the four delegated classes are imported
        INSIDE this method (not at module level) so that
        `python3 -m unittest discover` does NOT pick them up as
        discovered tests of THIS module. Module-level imports would
        cause each underlying class to be counted both in its own
        module and again here, inflating the suite count by four. The
        umbrella's net delta over Phase 22 is +1 — exactly this one
        method.
        """
        from tests.test_compat_jobs_create import TestCompatJobsCreate
        from tests.test_compat_jobs_outcome import TestCompatJobsOutcome
        from tests.test_compat_meter_completion import (
            TestCompatMeterCompletion,
        )
        from tests.test_compat_meter_tool_event import (
            TestCompatMeterToolEvent,
        )

        loader = unittest.defaultTestLoader
        suite = unittest.TestSuite()
        for cls in (
            TestCompatMeterCompletion,
            TestCompatJobsCreate,
            TestCompatJobsOutcome,
            TestCompatMeterToolEvent,
        ):
            suite.addTests(loader.loadTestsFromTestCase(cls))

        stream = io.StringIO()
        runner = unittest.TextTestRunner(stream=stream, verbosity=2)
        result = runner.run(suite)

        self.assertTrue(
            result.wasSuccessful(),
            msg=(
                'COMPAT-01/COMPAT-02 v1.4 top-level wire-compat regression: '
                '{f} failure(s), {e} error(s) across the four delegated '
                'tests/test_compat_*.py runners. Captured output:\n{out}'
            ).format(
                f=len(result.failures),
                e=len(result.errors),
                out=stream.getvalue(),
            ),
        )


if __name__ == '__main__':
    unittest.main()
