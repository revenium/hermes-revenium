#!/usr/bin/env python3
"""Drive the extracted library from two non-Hermes hosts and prove three things:

  1. Both classify successfully with a REAL model call.
  2. Neither imports anything Hermes — asserted, not assumed.
  3. Report the adapter cost per host in lines, which is the actual answer to
     "what does the non-portable 76% cost each new host?"

Run: python3 run_hosts.py            # real claude CLI calls (~5s each)
     python3 run_hosts.py --scripted # deterministic, no model call
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client, scripted_client  # noqa: E402
from hosts import claude_code, litellm_guardrail  # noqa: E402

SCRIPTED = "--scripted" in sys.argv
FIXTURES = SPIKE_DIR / "fixtures"


def assert_no_hermes():
    """The load-bearing claim: nothing Hermes-shaped got imported or touched."""
    bad = [m for m in sys.modules
           if m in ("classifier",) or m.startswith(("hermes", "agent."))]
    if bad:
        raise AssertionError(f"host adapter pulled in Hermes modules: {bad}")
    for name, mod in list(sys.modules.items()):
        origin = getattr(getattr(mod, "__spec__", None), "origin", None)
        if origin and ".hermes" in str(origin):
            raise AssertionError(f"module loaded from a Hermes tree: {name} <- {origin}")
    return True


def assert_extraction_nonempty(host: str, user: str, assistant: str):
    """FINDING: the library classifies empty input without complaint — it just
    calls the model with two empty previews and returns whatever comes back.
    Hermes' 'is this turn substantive' gating lives in the host-bound 76%, so
    every new host must re-implement this guard or it will burn an inference
    (and mint a junk label) on an empty extraction. My first Claude Code run
    parsed 0 turns and still produced a confident label — this assert exists
    because that silently 'passed'."""
    if not (user or assistant).strip():
        raise AssertionError(f"{host}: extraction produced no text — would classify nothing")


def code_lines(path: Path) -> int:
    """Executable lines only — docstrings and comments stripped."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return len([l for l in ast.unparse(tree).splitlines() if l.strip()])


def main() -> int:
    results = {}

    # ---- Host A: LiteLLM guardrail -------------------------------------------
    payload = json.loads((FIXTURES / "litellm-guardrail-payload.json").read_text())
    llm = scripted_client(["settlement_reconciliation_debug"]) if SCRIPTED else claude_cli_client()
    # No filesystem: a guardrail worker has nowhere durable to keep a vocabulary.
    tax_a = lib.InMemoryTaxonomy(seed=["research", "analysis", "code_review"])
    clf_a = lib.Classifier(llm=llm, taxonomy=tax_a, host="LiteLLM proxy")
    assert_extraction_nonempty("litellm_guardrail", *litellm_guardrail.extract_turn(payload))
    t0 = time.time()
    results["litellm_guardrail"] = litellm_guardrail.classify(payload, clf_a)
    results["litellm_guardrail"]["elapsed_s"] = round(time.time() - t0, 2)
    results["litellm_guardrail"]["taxonomy_after"] = tax_a.labels()

    # ---- Host B: Claude Code session -----------------------------------------
    session = FIXTURES / "claude-code-session.jsonl"
    llm_b = scripted_client(["spike_harness_build"]) if SCRIPTED else claude_cli_client()
    tax_b = lib.FileTaxonomy(SPIKE_DIR / "claude-code-taxonomy.json")
    clf_b = lib.Classifier(llm=llm_b, taxonomy=tax_b, host="Claude Code")
    _turns = claude_code.load_turns(session)
    assert_extraction_nonempty("claude_code", *claude_code.first_exchange(_turns))
    t0 = time.time()
    results["claude_code"] = claude_code.classify(session, clf_b)
    results["claude_code"]["elapsed_s"] = round(time.time() - t0, 2)
    results["claude_code"]["taxonomy_after"] = tax_b.labels()

    assert_no_hermes()

    print(json.dumps(results, indent=2))

    print("\nadapter cost (executable lines, docstrings/comments stripped)")
    print("-" * 62)
    lib_dir = SPIKE_DIR.parent / "001-extraction-seam" / "revenium_classify"
    lib_lines = sum(code_lines(p) for p in sorted(lib_dir.glob("*.py")))
    a = code_lines(SPIKE_DIR / "hosts" / "litellm_guardrail.py")
    b = code_lines(SPIKE_DIR / "hosts" / "claude_code.py")
    c = code_lines(SPIKE_DIR / "clients.py")
    print(f"  shared library (revenium_classify)   {lib_lines:>4}")
    print(f"  LiteLLM guardrail adapter            {a:>4}")
    print(f"  Claude Code adapter                  {b:>4}")
    print(f"  client shims (both hosts)            {c:>4}")
    print(f"\n  reuse ratio, LiteLLM host: {lib_lines}/{lib_lines+a} = {100*lib_lines/(lib_lines+a):.0f}% shared")
    print(f"  reuse ratio, Claude Code:  {lib_lines}/{lib_lines+b} = {100*lib_lines/(lib_lines+b):.0f}% shared")
    print("\nno-Hermes assertion: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
