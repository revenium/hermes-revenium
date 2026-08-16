#!/usr/bin/env python3
"""Measure the portable / host-bound split in classifier.py by AST, not by eye.

Each top-level function is classified by what it actually touches:
  HOST      — session DB, marker files, profile path resolution, halt state
  TAXONOMY  — the taxonomy JSON files (portable concept, file-backed impl)
  LLM       — invokes the injected model client
  PURE      — none of the above

Run: python3 analyze_split.py
"""
from __future__ import annotations

import ast
from pathlib import Path

def _repo_root(start: Path) -> Path:
    """Walk up until we find the repo (marker: skills/revenium). Depth-independent, so
    these harnesses work both at .planning/spikes/ and archived under .claude/skills/."""
    for parent in [start, *start.parents]:
        if (parent / "skills" / "revenium").is_dir():
            return parent
    raise RuntimeError(f"repo root not found above {start}")



REPO_ROOT = _repo_root(Path(__file__).resolve().parent)
SRC = REPO_ROOT / "skills" / "revenium" / "plugins" / "revenium-classifier" / "classifier.py"

HOST_MARKERS = {
    "sqlite3", "STATE_DB", "state_db", "markers_dir", "MARKERS_DIR",
    "markers_ready_dir", "MARKERS_READY_DIR", "_paths_for_session", "_module_paths",
    "guardrail_status_file", "GUARDRAIL_STATUS_FILE", "hermes_home", "HERMES_HOME",
    "_walk_to_root_session", "_write_marker_pair", "_write_job_marker",
    "_read_session_messages", "_read_session_transcript", "_guardrail_halted",
    "_job_marker_exists", "_read_latest_task_type", "_recent_marker_pair_exists",
    "_session_already_classified", "_root_agentic_job_id_for", "_NS_RE", "_Paths",
}
TAXONOMY_MARKERS = {"taxonomy_file", "job_taxonomy_file", "TAXONOMY_FILE", "JOB_TAXONOMY_FILE"}
LLM_MARKERS = {"call_llm"}


def names_in(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def main():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    rows = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        used = names_in(node)
        lines = (node.end_lineno or node.lineno) - node.lineno + 1
        if used & HOST_MARKERS:
            kind = "HOST"
        elif used & TAXONOMY_MARKERS:
            kind = "TAXONOMY"
        elif used & LLM_MARKERS:
            kind = "LLM"
        else:
            kind = "PURE"
        rows.append((kind, node.name, lines))

    total = sum(r[2] for r in rows)
    print(f"{SRC.relative_to(REPO_ROOT)} — {len(rows)} top-level functions, "
          f"{total} lines in function bodies (file is {len(SRC.read_text().splitlines())} lines)\n")
    print(f"{'kind':<9} {'function':<36} {'lines':>6}")
    print("-" * 54)
    for kind, name, lines in sorted(rows, key=lambda r: (r[0], -r[2])):
        print(f"{kind:<9} {name:<36} {lines:>6}")

    print("\nsummary")
    print("-" * 54)
    for kind in ("PURE", "LLM", "TAXONOMY", "HOST"):
        sub = [r for r in rows if r[0] == kind]
        n = sum(r[2] for r in sub)
        print(f"{kind:<9} {len(sub):>2} fns  {n:>5} lines  {100*n/total:5.1f}%")
    portable = sum(r[2] for r in rows if r[0] in ("PURE", "LLM", "TAXONOMY"))
    print(f"\nportable (PURE+LLM+TAXONOMY): {portable} lines, {100*portable/total:.1f}% of function bodies")
    print(f"host-bound:                   {total-portable} lines, {100*(total-portable)/total:.1f}%")


if __name__ == "__main__":
    main()
