#!/usr/bin/env python3
"""Differential test: extracted library vs the original classifier.py.

The claim under test is not "the library works" — it is "the library is
BEHAVIOR-IDENTICAL to the code it replaces". Anything less and extraction is a
rewrite, which is a much bigger ask than a refactor.

Every pure-surface function is driven with the same inputs through both
implementations and the outputs compared exactly (==, not approximately).

Run: python3 differential_test.py
"""
from __future__ import annotations

import importlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPIKE_DIR.parents[2]
PLUGIN_DIR = REPO_ROOT / "skills" / "revenium" / "plugins" / "revenium-classifier"

sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(PLUGIN_DIR))

# Point the original module's import-time path constants at a scratch dir.
_TMP = tempfile.mkdtemp(prefix="spike001-")
os.environ["HERMES_HOME"] = os.path.join(_TMP, "hh")
os.environ["REVENIUM_STATE_DIR"] = os.path.join(_TMP, "hh", "state", "revenium")
os.environ["REVENIUM_TAXONOMY_FILE"] = os.path.join(_TMP, "hh", "state", "revenium", "task-taxonomy.json")

import classifier as original  # noqa: E402  (original, Hermes-shaped module)
importlib.reload(original)

import revenium_classify as lib  # noqa: E402  (extracted core)

FAILURES = []
CHECKS = 0


def check(name, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append((name, want, got))


# ---------------------------------------------------------------------------
# 1. validate_label — full grammar surface plus fuzz
# ---------------------------------------------------------------------------
LABEL_CASES = [
    "", " ", "a", "ab", "code_review", "CODE_REVIEW", "  code_review  ",
    "ack", "ACK", "greeting", "thanks", "hello", "confirmation", "acknowledgment",
    "1bad", "_bad", "bad-label", "bad label", "bad.label", "bad:label", "bad|label",
    "x" * 48, "x" * 49, "a" + "b" * 46, "a" + "b" * 47,
    "café_review", "code_review\n", "code_review\nack", "unclassified",
    "a1", "a_", "a__b", "z9_9",
]
rng = random.Random(20260815)
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_-. |:\n\tABC"
for _ in range(4000):
    LABEL_CASES.append("".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 60))))

for case in LABEL_CASES:
    check(f"validate_label({case!r})", lib.validate_label(case), original._validate_label(case))

# ---------------------------------------------------------------------------
# 2. parse_job_array — fences, shapes, garbage
# ---------------------------------------------------------------------------
PARSE_CASES = [
    "", "   ", "null", "[]", "{}", "[{}]", "not json",
    '{"agentic_job_id":"a","job_type":"b","status":"SUCCESS"}',
    '[{"agentic_job_id":"a"},{"agentic_job_id":"b"}]',
    '```json\n[{"a":1}]\n```',
    '```json[{"a":1}]```',
    '```\n[{"a":1}]\n```',
    '```JSON\n[{"a":1}]\n```',
    '```python\n[{"a":1}]\n```',
    '[1,2,3]', '["a",{"b":2},3]', '[[1],{"c":3}]',
    '  \n ```json\n  [ { "x" : "y" } ]  \n``` \n ',
    '[{"a":1}', '{"a":1}]', '[{"a": "unterminated}',
    '[{"nested": {"deep": [1,2,{"k":"v"}]}}]',
    "[" + ",".join('{"i":%d}' % i for i in range(200)) + "]",
]
for _ in range(600):
    PARSE_CASES.append("".join(rng.choice('{}[]",:abc01 \n`') for _ in range(rng.randint(0, 40))))

for case in PARSE_CASES:
    check(f"parse_job_array({case[:40]!r})", lib.parse_job_array(case), original._parse_job_array(case))

# ---------------------------------------------------------------------------
# 3. validate_job — pin the entropy on both sides so the compare is exact
# ---------------------------------------------------------------------------
class _FixedSecrets:
    @staticmethod
    def token_hex(n):
        return "beef"


_real_secrets = original.secrets
original.secrets = _FixedSecrets

JOB_CASES = [
    None, "not a dict", 42, [], {},
    {"agentic_job_id": "", "job_type": "x_y", "status": "SUCCESS"},
    {"agentic_job_id": "  ", "job_type": "x_y", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "BUG_FIX", "status": "success"},
    {"agentic_job_id": "fix_auth", "job_type": "bug-fix", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "PENDING"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "FAILED"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "FAILED",
     "failure_reason": "  tests failed: 3 assertions  "},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "FAILED",
     "failure_reason": "z" * 900},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "SUCCESS",
     "failure_reason": "should be dropped"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "CANCELLED",
     "failure_reason": 12345},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "SUCCESS", "job_name": None},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": "SUCCESS", "job_name": "Fix auth"},
    {"agentic_job_id": 999, "job_type": "bug_fix", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": 999, "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "bug_fix", "status": 999},
    {"agentic_job_id": "inject\nJOB:evil", "job_type": "bug_fix", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "bug|fix", "status": "SUCCESS"},
    {"agentic_job_id": "fix_auth", "job_type": "x" * 60, "status": "SUCCESS"},
]
for case in JOB_CASES:
    got = lib.validate_job(case, entropy=lambda: "beef") if isinstance(case, dict) else lib.validate_job(case, entropy=lambda: "beef")
    check(f"validate_job({str(case)[:50]})", got, original._validate_job(case))

original.secrets = _real_secrets

# ---------------------------------------------------------------------------
# 4. Prompts — byte-identical at the default host
# ---------------------------------------------------------------------------
PROMPT_CASES = [
    ("", "", []),
    ("hello", "world", []),
    ("hello", "world", ["code_review", "research"]),
    ("u" * 2000, "a" * 2000, ["l_%d" % i for i in range(300)]),
    (None, None, []),
    ("unicode ☃ prompt", "résponse", ["café_review"]),
]
for user, asst, labels in PROMPT_CASES:
    check(
        f"classification_prompt({str(user)[:20]!r})",
        lib.build_classification_prompt(user, asst, labels),
        original._build_classification_prompt(user, asst, labels),
    )

JOB_PROMPT_CASES = [
    ("", []),
    ("a transcript", []),
    ("a transcript", ["bug_fix", "feature_development"]),
    ("t" * 9000, ["l_%d" % i for i in range(300)]),
    (None, []),
]
for transcript, labels in JOB_PROMPT_CASES:
    check(
        f"job_prompt({str(transcript)[:20]!r})",
        lib.build_job_inference_prompt(transcript, labels),
        original._build_job_inference_prompt(transcript, labels),
    )

# ---------------------------------------------------------------------------
# 5. Taxonomy read ordering — same file, same order
# ---------------------------------------------------------------------------
import datetime  # noqa: E402

tax_path = Path(os.environ["REVENIUM_TAXONOMY_FILE"])
tax_path.parent.mkdir(parents=True, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc)
fixture = {
    "labels": {
        "zeta_seed": {"description": "seed", "examples": []},
        "alpha_seed": {"description": "seed", "examples": []},
        "recent_one": {"last_seen_at": (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "recent_two": {"last_seen_at": (now - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "stale_one": {"last_seen_at": (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "corrupt_ts": {"last_seen_at": "not-a-timestamp"},
        "not_a_dict": "scalar",
    }
}
tax_path.write_text(json.dumps(fixture), encoding="utf-8")
importlib.reload(original)
check("taxonomy order", lib.FileTaxonomy(tax_path).labels(), original._read_taxonomy_labels())

tax_path.write_text("{ not json", encoding="utf-8")
check("taxonomy corrupt", lib.FileTaxonomy(tax_path).labels(), original._read_taxonomy_labels())

missing = tax_path.parent / "does-not-exist.json"
check("taxonomy missing", lib.FileTaxonomy(missing).labels(), [])

# Mint-back writes the same on-disk shape
tax_path.write_text(json.dumps({"labels": {}}), encoding="utf-8")
original._persist_label_to_taxonomy("orig_label")
orig_doc = json.loads(tax_path.read_text())
tax_path.write_text(json.dumps({"labels": {}}), encoding="utf-8")
lib.FileTaxonomy(tax_path).record("orig_label")
lib_doc = json.loads(tax_path.read_text())
check(
    "mint-back shape",
    sorted(lib_doc["labels"]["orig_label"].keys()),
    sorted(orig_doc["labels"]["orig_label"].keys()),
)
check("mint-back key", list(lib_doc["labels"].keys()), list(orig_doc["labels"].keys()))
tax_path.write_text(json.dumps({"labels": {}}), encoding="utf-8")
original._persist_label_to_taxonomy("unclassified")
before = tax_path.read_text()
lib.FileTaxonomy(tax_path).record("unclassified")
check("mint-back skips sentinel", tax_path.read_text(), before)

# ---------------------------------------------------------------------------
print(f"\ndifferential: {CHECKS} comparisons, {len(FAILURES)} mismatches")
for name, want, got in FAILURES[:20]:
    print(f"  MISMATCH {name}\n    original: {want!r}\n    library:  {got!r}")
sys.exit(1 if FAILURES else 0)
