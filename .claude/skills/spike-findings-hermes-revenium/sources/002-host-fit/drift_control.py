#!/usr/bin/env python3
"""Control experiment: is cross-host label disagreement caused by the host
framing, or is the model simply nondeterministic at temperature 0?

Without this control, "three hosts produced three labels" is not evidence of
anything — it could be three samples of a noisy distribution.

  Arm A (control): the SAME host word, N times. Isolates model nondeterminism.
  Arm B (treatment): the three host words, N times each. Framing + noise.

If Arm A is also unstable, framing is not the story and the finding is much
worse: the taxonomy cannot be stabilized by unifying prompts at all.

Run: python3 drift_control.py [--n 3]
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 3))
HOSTS = ["Hermes", "LiteLLM proxy", "Claude Code"]
SEEDS = ["research", "analysis", "code_review", "generation"]

USER = ("Our reconciliation job is dropping about 0.3% of settlement rows overnight. "
        "Here's the job config and last night's log tail — figure out where the rows are going.")
ASSISTANT = ("The drop is in the dedupe stage: settlement_id is compared after a lossy cast "
             "to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.")


def run(host: str) -> str:
    clf = lib.Classifier(
        llm=claude_cli_client(),
        taxonomy=lib.InMemoryTaxonomy(seed=SEEDS),
        host=host,
    )
    return clf.classify_turn(USER, ASSISTANT)


def main():
    t0 = time.time()
    control = [run("Hermes") for _ in range(N)]
    treatment = {h: [run(h) for _ in range(N)] for h in HOSTS}

    print(f"\nArm A (control) — host='Hermes' x{N}, identical prompt each time:")
    for label in control:
        print(f"    {label}")
    print(f"  distinct: {len(set(control))}/{N}")

    print(f"\nArm B (treatment) — each host x{N}:")
    for host, labels in treatment.items():
        print(f"  {host:<16} {labels}")
    all_treatment = [l for labels in treatment.values() for l in labels]
    print(f"  distinct across hosts: {len(set(all_treatment))}/{len(all_treatment)}")
    within = {h: len(set(labels)) for h, labels in treatment.items()}
    print(f"  distinct within each host: {within}")

    print("\ninterpretation")
    print("-" * 60)
    ctrl_unstable = len(set(control)) > 1
    if ctrl_unstable:
        print("  Control is UNSTABLE: the same prompt yields different labels.")
        print("  => Model nondeterminism dominates. Cross-host prompt unification")
        print("     would NOT stabilize the taxonomy. Drift is intrinsic to")
        print("     free-form minting, not to the library split.")
    else:
        print("  Control is STABLE: identical prompts reproduce one label.")
        print("  => The cross-host disagreement is attributable to host framing,")
        print("     which is a fixable, library-level design choice.")
    counts = collections.Counter(all_treatment + control)
    print(f"\n  label universe from {len(all_treatment)+len(control)} classifications of ONE piece of work: "
          f"{len(counts)} distinct")
    for label, c in counts.most_common():
        print(f"    {c}x  {label}")
    print(f"\n  elapsed {time.time()-t0:.0f}s")

    (SPIKE_DIR / "drift_control_result.json").write_text(json.dumps(
        {"control": control, "treatment": treatment,
         "control_stable": not ctrl_unstable,
         "distinct_labels_total": len(counts)}, indent=2))


if __name__ == "__main__":
    main()
