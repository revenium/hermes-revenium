#!/usr/bin/env python3
"""Can far-domain examples anchor granularity WITHOUT being copied?

Established so far:
  * the current examples get copied verbatim onto unrelated work (2-3/15) and
    steal reuse from apt labels already in the vocabulary (spike: 3/5 -> 4/5);
  * but deleting them wrecks the 2-4 word granularity they exist to anchor
    (14/15 in range -> 8/15), and the STATED rule does not substitute for the
    demonstrated pattern — the rule is present in every arm including FLOOR.

Hypothesis: copying happens because the current examples are semantically
ADJACENT to the work being classified (`sql_query_debug` looks like a plausible
label for a CI/test/database task). Examples drawn from a far domain should
anchor the shape while never being a plausible answer.

  CURRENT   weekly_pr_review, prod_log_triage, news_summary, sql_query_debug,
            release_notes_draft            (engineering-adjacent)
  FAR       recipe_scaling_math, travel_itinerary_draft, garden_layout_plan,
            bird_species_lookup, poem_meter_analysis   (same 2-4 word shape)

Both arms use the real seed and the same five engineering work items.
Measured: verbatim copying of an example, verbatim seed reuse, and word-count
granularity.

Run: python3 far_domain_examples.py [--n=3]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SPIKES = REPO / ".planning" / "spikes"
sys.path.insert(0, str(SPIKES / "001-extraction-seam"))
sys.path.insert(0, str(SPIKES / "002-host-fit"))
sys.path.insert(0, str(SPIKES / "003-taxonomy-drift"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402
from work_items import WORK  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 3))

SEED = list(json.loads((REPO / "skills" / "revenium" / "task-taxonomy.json").read_text())["labels"])
CURRENT = ["weekly_pr_review", "prod_log_triage", "news_summary",
           "sql_query_debug", "release_notes_draft"]
FAR = ["recipe_scaling_math", "travel_itinerary_draft", "garden_layout_plan",
       "bird_species_lookup", "poem_meter_analysis"]


def build(user_msg, assistant_resp, labels, examples) -> str:
    labels_block = ", ".join(labels) if labels else "(no existing labels yet)"
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    return (
        "You are classifying a Hermes session turn for spend attribution. "
        "Output ONLY a single snake_case label, no explanation, no quotes, no punctuation.\n\n"
        "Mint a SPECIFIC, DESCRIPTIVE label that captures what the agent actually did. "
        "Use 2-4 words joined by underscores. "
        f"Good examples: {', '.join(examples)}.\n\n"
        "AVOID bland catch-all labels like generation, analysis, review, task when a more specific label fits.\n\n"
        f"Existing labels (for reference): {labels_block}\n\n"
        "You MAY reuse one of the existing labels, but only if it describes the SAME specific work — "
        "not 'close enough'. If no existing label is an exact match for this work, mint a new one.\n\n"
        "Label format: ^[a-z][a-z0-9_]{1,47}$\n"
        "Forbidden labels (do NOT emit): ack, acknowledgment, greeting, confirmation, hello, thanks.\n\n"
        f"User message preview:\n{(user_msg or '')[:800]}\n\n"
        f"Assistant response preview:\n{(assistant_resp or '')[:800]}\n\n"
        "Label:"
    )


def classify(prompt: str) -> str:
    call = claude_cli_client()
    resp = call(messages=[
        {"role": "system", "content": "You classify Hermes turns into task_type labels. Output only the label."},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=64, timeout=30.0)
    return lib.validate_label((resp.choices[0].message.content or "").strip())


def main():
    t0, out = time.time(), {}
    for arm, examples in (("CURRENT (engineering-adjacent)", CURRENT), ("FAR (unrelated domains)", FAR)):
        labels, buckets = [], Counter()
        for _ in range(N):
            for item in WORK:
                l = classify(build(item["user"], item["assistant"], SEED, examples))
                labels.append((item["id"], l))
                if l in examples:
                    buckets["example_verbatim"] += 1
                elif l in SEED:
                    buckets["seed_verbatim"] += 1
                elif l == "unclassified":
                    buckets["unclassified"] += 1
                else:
                    buckets["minted"] += 1
        wc = [len(l.split("_")) for _, l in labels if l != "unclassified"]
        inrange = sum(1 for w in wc if 2 <= w <= 4)
        out[arm] = {"labels": labels, "buckets": dict(buckets),
                    "mean_words": round(statistics.mean(wc), 2),
                    "in_range": f"{inrange}/{len(wc)}"}
        total = sum(buckets.values())
        bad = buckets["example_verbatim"] + buckets["seed_verbatim"]
        print(f"{arm}")
        print(f"   verbatim-reuse {bad}/{total}   "
              f"({buckets['example_verbatim']} example, {buckets['seed_verbatim']} seed)   "
              f"mean words {out[arm]['mean_words']}   in 2-4 range {out[arm]['in_range']}")
        for wid, l in labels:
            mark = "  <-- COPIED" if l in examples else ("  <-- seed" if l in SEED else "")
            print(f"     {wid:<8} {l}{mark}")
        print()

    cur, far = out["CURRENT (engineering-adjacent)"], out["FAR (unrelated domains)"]
    print("interpretation")
    print("-" * 66)
    cur_bad = cur["buckets"].get("example_verbatim", 0) + cur["buckets"].get("seed_verbatim", 0)
    far_bad = far["buckets"].get("example_verbatim", 0) + far["buckets"].get("seed_verbatim", 0)
    print(f"  verbatim reuse : current {cur_bad}  ->  far-domain {far_bad}")
    print(f"  granularity    : current {cur['in_range']} ({cur['mean_words']} words)  ->  "
          f"far-domain {far['in_range']} ({far['mean_words']} words)")
    if far_bad < cur_bad and far["mean_words"] <= cur["mean_words"] + 0.6:
        print("  Far-domain examples anchor the shape WITHOUT being copied. Ship them.")
    elif far_bad < cur_bad:
        print("  Copying drops but granularity loosens — weigh the trade before shipping.")
    else:
        print("  Far-domain examples do NOT reduce copying; the adjacency hypothesis fails.")
    print(f"\n  elapsed {time.time()-t0:.0f}s")
    (HERE / "far_domain_result.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
