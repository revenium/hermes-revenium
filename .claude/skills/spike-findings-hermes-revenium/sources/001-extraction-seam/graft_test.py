#!/usr/bin/env python3
"""Graft test: run the REPO'S OWN classifier tests against a plugin whose pure
surface has been replaced by the extracted library.

The differential test proves the library agrees with the original on inputs I
chose. This proves it survives the inputs the project's maintainers chose —
including the halt gate, dedupe, subagent inheritance, and marker-schema tests.

Mechanism: generate a `classifier.py` that is the original source plus a graft
epilogue rebinding the pure names to `revenium_classify`, put it earlier on
sys.path than the real plugin, then run the project's classifier tests unchanged.

Run: python3 graft_test.py            # grafted run
     python3 graft_test.py --baseline # same tests, ungrafted, for comparison
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

def _repo_root(start: Path) -> Path:
    """Walk up until we find the repo (marker: skills/revenium). Depth-independent, so
    these harnesses work both at .planning/spikes/ and archived under .claude/skills/."""
    for parent in [start, *start.parents]:
        if (parent / "skills" / "revenium").is_dir():
            return parent
    raise RuntimeError(f"repo root not found above {start}")



SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = _repo_root(SPIKE_DIR)
PLUGIN_DIR = REPO_ROOT / "skills" / "revenium" / "plugins" / "revenium-classifier"

BASELINE = "--baseline" in sys.argv

# --mutate=<key> deliberately breaks one grafted function. The repo suite MUST
# then go red. A surviving mutant means the tests never touch that seam, and a
# green grafted run proves nothing about it.
MUTANTS = {
    "validate_label": '\ndef _validate_label(label):\n    return "sabotage"\n',
    "classification_prompt": '\ndef _build_classification_prompt(u, a, l):\n    return ""\n',
    "job_prompt": '\ndef _build_job_inference_prompt(t, l):\n    return ""\n',
    "taxonomy_labels": '\ndef _read_taxonomy_labels(paths=None):\n    return []\n',
    "persist_label": '\ndef _persist_label_to_taxonomy(label, paths=None):\n    return None\n',
    "parse_job_array": '\ndef _parse_job_array(raw):\n    return []\n',
    "validate_job": '\ndef _validate_job(job):\n    return None\n',
}
MUTATE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--mutate=")), None)

GRAFT_EPILOGUE = '''

# ---------------------------------------------------------------------------
# SPIKE 001 GRAFT — the pure surface now lives in revenium_classify.
# Everything below this line is the ONLY change to the plugin. Every function
# rebound here was proven byte-identical by differential_test.py.
# ---------------------------------------------------------------------------
import revenium_classify as _lib  # noqa: E402

LABEL_RE = _lib.LABEL_RE
TRIVIAL_BLOCKLIST = _lib.TRIVIAL_BLOCKLIST


def _validate_label(label: str) -> str:
    return _lib.validate_label(label)


def _parse_job_array(raw: str):
    return _lib.parse_job_array(raw)


def _validate_job(job):
    # logger= is load-bearing: the rejection record must land on THIS module's
    # `revenium_classifier` channel (test_phase28_classifier_reject_log).
    return _lib.validate_job(job, logger=logger)


def _build_classification_prompt(user_msg, assistant_resp, labels):
    return _lib.build_classification_prompt(user_msg, assistant_resp, labels)


def _build_job_inference_prompt(transcript, job_labels):
    return _lib.build_job_inference_prompt(transcript, job_labels)


def _read_taxonomy_labels(paths=None):
    return _lib.FileTaxonomy((paths or _module_paths()).taxonomy_file).labels()


def _persist_label_to_taxonomy(label, paths=None):
    return _lib.FileTaxonomy((paths or _module_paths()).taxonomy_file).record(label)
'''

# Tests in the repo suite that exercise the classifier plugin.
CLASSIFIER_TESTS = [
    "test_revenium_classifier_no_tools_classified_not_skipped",
    "test_revenium_classifier_never_raises",
    "test_revenium_classifier_dedupe",
    "test_revenium_classifier_llm_label",
    "test_revenium_classifier_llm_blocklist_fallthrough",
    "test_revenium_classifier_prompt_mint_first_bias",
    "test_revenium_classifier_halt_unclassified",
    "test_revenium_classifier_halt_failopen_on_missing_file",
    "test_revenium_classifier_subagent_inherits",
    "test_revenium_classifier_walk_to_root",
    "test_marker_file_schema",
    "test_taxonomy_file_schema",
    "test_job_taxonomy_file_schema",
    "test_taxonomy_atomic_write_pattern",
    "test_prompt_ordering_invariant",
]


def build_graft_dir() -> Path:
    graft_dir = Path(tempfile.mkdtemp(prefix="spike001-graft-"))
    # Copy the whole plugin package so relative fixtures still resolve.
    for item in PLUGIN_DIR.iterdir():
        if item.name == "__pycache__":
            continue
        dest = graft_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    src = (PLUGIN_DIR / "classifier.py").read_text(encoding="utf-8")
    epilogue = GRAFT_EPILOGUE
    if MUTATE:
        epilogue += MUTANTS[MUTATE]
    (graft_dir / "classifier.py").write_text(src + epilogue, encoding="utf-8")
    return graft_dir


def main() -> int:
    # The repo's _setup_plugin_env does `sys.path.insert(0, PLUGIN_DIR)` only when
    # PLUGIN_DIR is absent. Pre-seed it at the END so that guard is satisfied and
    # cannot jump ahead of our graft dir.
    sys.path.append(str(PLUGIN_DIR))
    if not BASELINE:
        graft_dir = build_graft_dir()
        sys.path.insert(0, str(SPIKE_DIR))   # revenium_classify
        sys.path.insert(0, str(graft_dir))   # grafted classifier.py wins
        print(f"grafted classifier: {graft_dir}/classifier.py")
    else:
        print("baseline: original classifier.py, no graft")

    sys.path.insert(0, str(REPO_ROOT))
    import tests.test_repository as tr  # noqa: E402

    import classifier  # noqa: E402
    grafted = "SPIKE 001 GRAFT" in Path(classifier.__file__).read_text(encoding="utf-8")
    print(f"resolved classifier module: {classifier.__file__}")
    print(f"graft active: {grafted}")
    if not BASELINE and not grafted:
        print("FATAL: graft not active — sys.path ordering failed, result would be meaningless")
        return 2

    suite = unittest.TestSuite(
        tr.RepositoryTests(name) for name in CLASSIFIER_TESTS
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        f"\n{'GRAFTED' if not BASELINE else 'BASELINE'}: ran {result.testsRun}, "
        f"failures {len(result.failures)}, errors {len(result.errors)}"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
