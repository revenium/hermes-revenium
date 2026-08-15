#!/usr/bin/env python3
"""Re-do the wall-clock arm properly, and find out whether it is measurable at all.

The first attempt ran all baseline calls, then all classification calls, and
reported classification as 0.64s FASTER than a two-token prompt. That is an
ordering artifact: the baseline block absorbed the cold start (its max was
16.1s vs a 5.2s floor).

This version interleaves the two conditions so any warm-up drift hits both
equally, and reports min as well as median — min is the least-contaminated
estimate when the noise is all additive startup cost.

The hypothesis being tested is now explicitly: *can this instrument detect the
difference at all?* If the two distributions overlap, the answer is no, and the
honest output of spike 004 is a bound plus a structural argument, not a number.

Run: python3 wall_clock_interleaved.py [--n=6]
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))
sys.path.insert(0, str(SPIKE_DIR.parent / "002-host-fit"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 6))

USER = ("Our reconciliation job is dropping about 0.3% of settlement rows overnight. "
        "Here's the job config and last night's log tail — figure out where the rows are going.")
ASSISTANT = ("The drop is in the dedupe stage: settlement_id is compared after a lossy cast "
             "to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.")


def main():
    clf = lib.Classifier(llm=claude_cli_client(),
                         taxonomy=lib.InMemoryTaxonomy(seed=["research", "analysis"]),
                         host="LiteLLM proxy")
    base, cls = [], []
    # One warm-up call, discarded, so the cold start lands in neither condition.
    subprocess.run(["claude", "-p", "ok"], capture_output=True, text=True, timeout=90)
    for i in range(N):
        t0 = time.time()
        subprocess.run(["claude", "-p", "ok"], capture_output=True, text=True, timeout=90)
        base.append(time.time() - t0)
        t0 = time.time()
        clf.classify_turn(USER, ASSISTANT)
        cls.append(time.time() - t0)
        print(f"  pair {i+1}: baseline {base[-1]:.2f}s  classification {cls[-1]:.2f}s")

    print(f"\nbaseline        n={N}  min {min(base):.2f}  median {statistics.median(base):.2f}  max {max(base):.2f}")
    print(f"classification  n={N}  min {min(cls):.2f}  median {statistics.median(cls):.2f}  max {max(cls):.2f}")
    d_min = min(cls) - min(base)
    d_med = statistics.median(cls) - statistics.median(base)
    print(f"\ndelta (min)     {d_min:+.2f}s")
    print(f"delta (median)  {d_med:+.2f}s")

    overlap = not (min(cls) > max(base) or min(base) > max(cls))
    print("\ninstrument check")
    print("-" * 60)
    if overlap:
        print("  The two distributions OVERLAP. The claude-CLI harness cannot resolve")
        print("  the added inference latency — process startup and auth dominate.")
        print("  => Spike 004 must answer structurally + by token count, NOT with a")
        print("     wall-clock number from this instrument. Any latency figure quoted")
        print("     from this harness would be noise dressed as a measurement.")
    else:
        print("  Distributions are separated; the delta above is meaningful for THIS")
        print("  client, though still not an API measurement.")

    (SPIKE_DIR / "wall_clock_result.json").write_text(json.dumps({
        "baseline_s": base, "classification_s": cls,
        "delta_min_s": round(d_min, 2), "delta_median_s": round(d_med, 2),
        "distributions_overlap": overlap,
    }, indent=2))


if __name__ == "__main__":
    main()
