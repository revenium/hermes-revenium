#!/usr/bin/env python3
"""Which attractor actually pulls the classifier toward inapt labels?

Spike 003 observed a CI-flakiness investigation labelled `sql_query_debug` and a
security review labelled `prod_log_triage`, and attributed both to the seed
taxonomy. That attribution was WRONG: neither is a seed label. Both are among the
five hardcoded "Good examples" inside the prompt string itself
(classifier.py:787). `code_review` — which the same item also drew — IS a seed
label, so seed-reuse is real too.

There are therefore TWO candidate attractors, and the fix depends on which one
dominates:

  A) the seed vocabulary   (skills/revenium/task-taxonomy.json, 8 generic labels)
  B) the prompt's examples (weekly_pr_review, prod_log_triage, news_summary,
                            sql_query_debug, release_notes_draft)

2x2 factorial, five work items per cell, all unrelated to both label sets:

              | examples present | examples removed
  seed present|  BASELINE        |  SEED_ONLY
  seed empty  |  EXAMPLES_ONLY   |  FLOOR

Outcome for each classification is classified objectively by string identity —
no judgement call:
  seed_verbatim     output is exactly one of the 8 seed labels
  example_verbatim  output is exactly one of the 5 prompt examples
  minted            anything else (the desired behavior)

CONFOUND (inherited): the claude CLI client cannot pass temperature=0.

Run: python3 seed_attractor_experiment.py [--n=1]
"""
from __future__ import annotations

import json
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

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 1))

SEED = list(json.loads((REPO / "skills" / "revenium" / "task-taxonomy.json").read_text())["labels"])
EXAMPLES = ["weekly_pr_review", "prod_log_triage", "news_summary",
            "sql_query_debug", "release_notes_draft"]

EXAMPLES_SENTENCE = (
    "Use 2-4 words joined by underscores. "
    "Good examples: weekly_pr_review, prod_log_triage, news_summary, sql_query_debug, "
    "release_notes_draft.\n\n"
)
NO_EXAMPLES_SENTENCE = "Use 2-4 words joined by underscores.\n\n"


def build_prompt(user_msg, assistant_resp, labels, with_examples: bool) -> str:
    """Mirror of lib.build_classification_prompt with the examples sentence toggled."""
    labels_block = ", ".join(labels) if labels else "(no existing labels yet)"
    if len(labels_block) > 1024:
        labels_block = labels_block[:1024] + " ... [truncated]"
    return (
        "You are classifying a Hermes session turn for spend attribution. "
        "Output ONLY a single snake_case label, no explanation, no quotes, no punctuation.\n\n"
        "Mint a SPECIFIC, DESCRIPTIVE label that captures what the agent actually did. "
        + (EXAMPLES_SENTENCE if with_examples else NO_EXAMPLES_SENTENCE) +
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


ARMS = {
    "BASELINE      (seed + examples)": (SEED, True),
    "SEED_ONLY     (seed, no examples)": (SEED, False),
    "EXAMPLES_ONLY (no seed, examples)": ([], True),
    "FLOOR         (no seed, no examples)": ([], False),
}


def classify(prompt: str) -> str:
    call = claude_cli_client()
    resp = call(messages=[
        {"role": "system", "content": "You classify Hermes turns into task_type labels. Output only the label."},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=64, timeout=30.0)
    raw = resp.choices[0].message.content
    return lib.validate_label((raw or "").strip())


def bucket(label: str) -> str:
    if label in SEED:
        return "seed_verbatim"
    if label in EXAMPLES:
        return "example_verbatim"
    if label == "unclassified":
        return "unclassified"
    return "minted"


def main():
    t0 = time.time()
    results = {}
    for arm, (labels, with_examples) in ARMS.items():
        outcomes, emitted = Counter(), []
        for _ in range(N):
            for item in WORK:
                label = classify(build_prompt(item["user"], item["assistant"], labels, with_examples))
                outcomes[bucket(label)] += 1
                emitted.append((item["id"], label))
        results[arm] = {"outcomes": dict(outcomes), "emitted": emitted}
        total = sum(outcomes.values())
        bad = outcomes["seed_verbatim"] + outcomes["example_verbatim"]
        print(f"{arm}")
        print(f"   {'  '.join(f'{k}={v}' for k, v in sorted(outcomes.items()))}"
              f"   -> verbatim-reuse {bad}/{total}")
        for wid, label in emitted:
            tag = bucket(label)
            mark = "  <-- " + tag if tag in ("seed_verbatim", "example_verbatim") else ""
            print(f"     {wid:<8} {label}{mark}")
        print()

    print("interpretation")
    print("-" * 66)
    base = results["BASELINE      (seed + examples)"]["outcomes"]
    seed_only = results["SEED_ONLY     (seed, no examples)"]["outcomes"]
    ex_only = results["EXAMPLES_ONLY (no seed, examples)"]["outcomes"]
    floor = results["FLOOR         (no seed, no examples)"]["outcomes"]
    print(f"  baseline verbatim-reuse : {base.get('seed_verbatim',0)} seed + {base.get('example_verbatim',0)} example")
    print(f"  removing examples       : {seed_only.get('seed_verbatim',0)} seed + {seed_only.get('example_verbatim',0)} example")
    print(f"  removing seed           : {ex_only.get('seed_verbatim',0)} seed + {ex_only.get('example_verbatim',0)} example")
    print(f"  removing both           : {floor.get('seed_verbatim',0)} seed + {floor.get('example_verbatim',0)} example")
    print(f"\n  elapsed {time.time()-t0:.0f}s")
    (HERE / "seed_attractor_result.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
