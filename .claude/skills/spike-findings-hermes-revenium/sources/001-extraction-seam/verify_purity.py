#!/usr/bin/env python3
"""Assert the extracted library is genuinely host-agnostic.

Three checks:
  1. Importing it pulls in no non-stdlib module (no hermes, no agent, no openai).
  2. Its source contains no Hermes-specific identifier.
  3. It classifies end-to-end with a fake LLM and an in-memory taxonomy — i.e.
     with no filesystem and no session database at all.

Run: python3 verify_purity.py
"""
from __future__ import annotations

import sys
import sysconfig
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))

STDLIB = Path(sysconfig.get_paths()["stdlib"]).resolve()
before = set(sys.modules)

import revenium_classify as lib  # noqa: E402

failures = []

# --- 1. no non-stdlib imports -------------------------------------------------
foreign = []
for name in set(sys.modules) - before:
    mod = sys.modules.get(name)
    origin = getattr(getattr(mod, "__spec__", None), "origin", None)
    if not origin or origin in ("built-in", "frozen"):
        continue
    p = Path(origin).resolve()
    if STDLIB in p.parents or str(p).startswith(str(SPIKE_DIR)):
        continue
    foreign.append(f"{name} <- {p}")
if foreign:
    failures.append("non-stdlib imports pulled in: " + ", ".join(foreign))

# --- 2. no host identifiers in the source ------------------------------------
BANNED = ["agent.auxiliary_client", "state.db", "sqlite3", "HERMES_HOME",
          "REVENIUM_STATE_DIR", "markers", "guardrail"]
import ast  # noqa: E402


def strip_docs(tree):
    """Drop docstrings so prose about the host contract isn't mistaken for code."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


pkg = SPIKE_DIR / "revenium_classify"
for py in sorted(pkg.glob("*.py")):
    text = py.read_text(encoding="utf-8")
    # Comments and docstrings legitimately discuss Hermes, guardrails, and the
    # host contract. Only executable code may not reference them.
    code = ast.unparse(strip_docs(ast.parse(text)))
    hits = [b for b in BANNED if b in code]
    if hits:
        failures.append(f"{py.name} references host-specific identifiers in code: {hits}")

# --- 3. end-to-end with no filesystem and no session DB ----------------------
class FakeResponse:
    class _C:
        class _M:
            content = "weekly_pr_review"
        message = _M()
    choices = [_C()]


def fake_llm(**kwargs):
    return FakeResponse()


tax = lib.InMemoryTaxonomy(seed=["research"])
clf = lib.Classifier(llm=fake_llm, taxonomy=tax, host="LiteLLM")
label = clf.classify_turn("review the open PRs", "Here are the 3 open PRs...")
if label != "weekly_pr_review":
    failures.append(f"end-to-end label wrong: {label!r}")
if "weekly_pr_review" not in tax.labels():
    failures.append("mint-back did not reach the in-memory taxonomy")

# The host name must actually reach the prompt.
prompt = lib.build_classification_prompt("u", "a", [], host="LiteLLM")
if "LiteLLM session turn" not in prompt:
    failures.append("host parameter did not reach the prompt")
if "Hermes" in prompt:
    failures.append("host default leaked into a non-Hermes prompt")

print(f"purity: {'FAIL' if failures else 'PASS'} ({len(failures)} problems)")
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)
