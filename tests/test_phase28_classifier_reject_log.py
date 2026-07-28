"""Phase 28 Plan 02 (Task 2): _validate_job records why a label was rejected.

D-09: a job dict whose job_type fails the label grammar must produce exactly
one WARNING record on the revenium_classifier logger before _validate_job
returns nothing, distinguishing "the label was rejected" from "inference
never ran" for anyone reading Hermes' gateway logs.

T-28-07: the rejected value must be rendered through the logger's lazy %r
argument, not an f-string or %s, so a newline/control character in the raw
(still-unvalidated) LLM response cannot forge a second log record.
"""
import importlib
import logging
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "skills" / "revenium" / "plugins" / "revenium-classifier"


class ClassifierRejectLogTests(unittest.TestCase):
    def setUp(self):
        self._path_added = str(PLUGIN_DIR) not in sys.path
        if self._path_added:
            sys.path.insert(0, str(PLUGIN_DIR))
        import classifier
        self.classifier = importlib.reload(classifier)

    def tearDown(self):
        if self._path_added:
            try:
                sys.path.remove(str(PLUGIN_DIR))
            except ValueError:
                pass

    def test_validate_job_logs_label_rejection(self):
        """An invalid job_type produces exactly one WARNING record and
        _validate_job still returns None."""
        job = {
            "agentic_job_id": "some-job",
            "job_type": "NOT A VALID LABEL!!",
            "status": "SUCCESS",
        }
        with self.assertLogs("revenium_classifier", level="WARNING") as cm:
            result = self.classifier._validate_job(job)
        self.assertIsNone(result)
        self.assertEqual(len(cm.records), 1)
        self.assertEqual(cm.records[0].levelname, "WARNING")

    def test_validate_job_rejection_uses_repr(self):
        """The emitted record's message carries the rejected value rendered
        through repr, so an embedded newline appears escaped rather than
        splitting the record into two lines."""
        malicious_job_type = "bad\nlabel INJECTED"
        job = {
            "agentic_job_id": "some-job",
            "job_type": malicious_job_type,
            "status": "SUCCESS",
        }
        with self.assertLogs("revenium_classifier", level="WARNING") as cm:
            result = self.classifier._validate_job(job)
        self.assertIsNone(result)
        self.assertEqual(len(cm.records), 1)
        message = cm.records[0].getMessage()
        # repr() escapes the newline as the two-character sequence \n rather
        # than emitting a real line break.
        self.assertIn(repr(malicious_job_type.strip().lower()), message)
        self.assertNotIn("\n", message)

    def test_validate_job_valid_label_logs_nothing(self):
        """A job dict with a valid job_type produces zero WARNING records
        and returns a normalized mapping."""
        job = {
            "agentic_job_id": "fix_auth_regression",
            "job_type": "code_review",
            "status": "SUCCESS",
        }
        logger = logging.getLogger("revenium_classifier")
        records = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _CaptureHandler(level=logging.WARNING)
        logger.addHandler(handler)
        try:
            result = self.classifier._validate_job(job)
        finally:
            logger.removeHandler(handler)

        warning_records = [r for r in records if r.levelno >= logging.WARNING]
        self.assertEqual(len(warning_records), 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["job_type"], "code_review")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertTrue(result["agentic_job_id"].startswith("fix_auth_regression_"))


if __name__ == '__main__':
    unittest.main()
