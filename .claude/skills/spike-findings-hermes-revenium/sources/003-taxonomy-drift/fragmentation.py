#!/usr/bin/env python3
"""Do independently-warmed hosts converge on DIFFERENT attractors, and does a
shared vocabulary eliminate it?

Spike 002 established that drift is cold-start-bounded: a vocabulary holding an
apt label converges 8/8. The question left over is what happens when three hosts
each pay their own cold start.

  ARM INDEPENDENT — three hosts, three separate taxonomy files, all starting from
                    the same generic seed. Each classifies the same work stream and
                    mints into its own vocabulary.
  ARM SHARED      — three hosts, ONE taxonomy store between them (what a served
                    vocabulary would look like). Same work stream, same order.

Metrics:
  * cross-host agreement — for each work item, how many distinct labels did the
    three hosts produce?
  * fragmentation ratio — distinct labels minted / distinct underlying activities.
    1.0 is perfect; higher means the same work is being split across rows in
    Revenium's analytics.
  * same-activity collision — flaky-1 and flaky-2 are the same activity described
    differently. Do they land on one label?

CONFOUND (inherited from 002): the claude CLI client cannot pass temperature=0.

Run: python3 fragmentation.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))
sys.path.insert(0, str(SPIKE_DIR.parent / "002-host-fit"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402
from work_items import DISTINCT_ACTIVITIES, SAME_ACTIVITY_PAIRS, WORK  # noqa: E402

HOSTS = ["Hermes", "LiteLLM proxy", "Claude Code"]
GENERIC_SEED = ["research", "analysis", "code_review", "generation"]


def run_arm(shared: bool) -> dict:
    """Classify the whole work stream through every host, in the same order."""
    if shared:
        store = lib.InMemoryTaxonomy(seed=list(GENERIC_SEED))
        stores = {h: store for h in HOSTS}
    else:
        stores = {h: lib.InMemoryTaxonomy(seed=list(GENERIC_SEED)) for h in HOSTS}

    labels = {}          # work_id -> {host: label}
    for item in WORK:
        labels[item["id"]] = {}
        for host in HOSTS:
            clf = lib.Classifier(llm=claude_cli_client(), taxonomy=stores[host], host=host)
            labels[item["id"]][host] = clf.classify_turn(item["user"], item["assistant"])

    minted = set()
    for per_host in labels.values():
        minted |= set(per_host.values())
    minted -= set(GENERIC_SEED)

    agreement = {
        wid: len(set(per_host.values()))
        for wid, per_host in labels.items()
    }
    collisions = {}
    for a, b in SAME_ACTIVITY_PAIRS:
        collisions[f"{a}~{b}"] = {
            host: (labels[a][host] == labels[b][host]) for host in HOSTS
        }

    return {
        "labels": labels,
        "distinct_labels_minted": sorted(minted),
        "fragmentation_ratio": round(len(set().union(*[set(v.values()) for v in labels.values()]))
                                     / DISTINCT_ACTIVITIES, 2),
        "per_item_distinct_labels": agreement,
        "mean_labels_per_item": round(sum(agreement.values()) / len(agreement), 2),
        "same_activity_collapsed": collisions,
        "final_vocabulary_size": {h: len(stores[h].labels()) for h in HOSTS},
    }


def main():
    t0 = time.time()
    print("ARM 1: INDEPENDENT vocabularies (one taxonomy per host)")
    independent = run_arm(shared=False)
    for wid, per_host in independent["labels"].items():
        print(f"  {wid:<8} " + " | ".join(f"{h.split()[0]}={l}" for h, l in per_host.items()))
    print(f"  mean distinct labels per work item: {independent['mean_labels_per_item']}")
    print(f"  fragmentation ratio: {independent['fragmentation_ratio']} "
          f"({DISTINCT_ACTIVITIES} real activities)")

    print("\nARM 2: SHARED vocabulary (one taxonomy for all three hosts)")
    shared = run_arm(shared=True)
    for wid, per_host in shared["labels"].items():
        print(f"  {wid:<8} " + " | ".join(f"{h.split()[0]}={l}" for h, l in per_host.items()))
    print(f"  mean distinct labels per work item: {shared['mean_labels_per_item']}")
    print(f"  fragmentation ratio: {shared['fragmentation_ratio']} "
          f"({DISTINCT_ACTIVITIES} real activities)")

    print("\nsame-activity collapse (flaky-1 vs flaky-2 — identical activity, different words)")
    for arm_name, arm in (("INDEPENDENT", independent), ("SHARED", shared)):
        for pair, per_host in arm["same_activity_collapsed"].items():
            hits = sum(1 for v in per_host.values() if v)
            print(f"  {arm_name:<12} {pair}: collapsed to one label in {hits}/{len(HOSTS)} hosts")

    print("\nverdict")
    print("-" * 62)
    delta = independent["mean_labels_per_item"] - shared["mean_labels_per_item"]
    print(f"  mean labels/item  independent {independent['mean_labels_per_item']} "
          f"-> shared {shared['mean_labels_per_item']}  (delta {delta:+.2f})")
    print(f"  fragmentation     independent {independent['fragmentation_ratio']} "
          f"-> shared {shared['fragmentation_ratio']}")
    if shared["mean_labels_per_item"] < independent["mean_labels_per_item"]:
        print("  A shared vocabulary measurably reduces cross-host fragmentation.")
    else:
        print("  A shared vocabulary did NOT reduce fragmentation — the cold-start")
        print("  window dominates and sharing alone is not the fix.")
    print(f"\n  elapsed {time.time()-t0:.0f}s")

    (SPIKE_DIR / "fragmentation_result.json").write_text(
        json.dumps({"independent": independent, "shared": shared}, indent=2))


if __name__ == "__main__":
    main()
