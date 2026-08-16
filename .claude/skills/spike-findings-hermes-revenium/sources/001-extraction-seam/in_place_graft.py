#!/usr/bin/env python3
"""In-place graft: temporarily replace the REAL plugin file with the grafted
version and run the FULL repo suite (324 tests).

Why this and not graft_test.py: much of the plugin's coverage runs the file from
its real path through bash/subprocess, so a sys.path graft is invisible to it.
This is the only way to answer "would the extraction survive the actual suite".

Safety: the original file is restored in a finally block AND verified against a
sha256 taken before the patch. `skills/` must be git-clean before running.

Run: python3 in_place_graft.py [--mutate=<key>]
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
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
TARGET = PLUGIN_DIR / "classifier.py"
VENDORED = PLUGIN_DIR / "revenium_classify"

sys.path.insert(0, str(SPIKE_DIR))
from graft_test import GRAFT_EPILOGUE, MUTANTS  # noqa: E402

MUTATE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--mutate=")), None)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "skills/"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        print(f"REFUSING: skills/ is not git-clean:\n{dirty}")
        return 2

    original = TARGET.read_bytes()
    before = sha(TARGET)
    epilogue = GRAFT_EPILOGUE + (MUTANTS[MUTATE] if MUTATE else "")
    # The library must sit beside the plugin so the plugin's own import works
    # regardless of how the test harness loads it.
    import shutil
    if VENDORED.exists():
        shutil.rmtree(VENDORED)
    shutil.copytree(SPIKE_DIR / "revenium_classify", VENDORED)

    try:
        TARGET.write_text(original.decode("utf-8") + epilogue, encoding="utf-8")
        label = f"mutant={MUTATE}" if MUTATE else "grafted (no mutation)"
        print(f"=== running FULL suite against {label} ===")
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        lines = proc.stderr.strip().splitlines()
        for ln in lines:
            if ln.startswith(("FAIL:", "ERROR:")):
                print("  " + ln)
        print("\n".join(lines[-4:]))
        (SPIKE_DIR / f"fullsuite-{MUTATE or 'graft'}.log").write_text(proc.stderr, encoding="utf-8")
        return 0 if proc.returncode == 0 else 1
    finally:
        TARGET.write_bytes(original)
        if VENDORED.exists():
            shutil.rmtree(VENDORED)
        after = sha(TARGET)
        print(f"restore verified: {after == before} ({after[:12]})")
        # Belt and braces: also confirm git agrees the tree is clean again.
        dirty2 = subprocess.run(
            ["git", "status", "--porcelain", "skills/"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        ).stdout.strip()
        print(f"git clean after restore: {not dirty2}")


if __name__ == "__main__":
    sys.exit(main())
