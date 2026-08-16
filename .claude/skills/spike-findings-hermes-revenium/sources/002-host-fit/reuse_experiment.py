#!/usr/bin/env python3
"""Does taxonomy reuse dampen the drift the control experiment exposed?

drift_control.py showed 11 distinct labels from 12 classifications of one piece
of work, with an unstable control. But it seeded the taxonomy with four generic
labels, which is NOT the production dynamic: the real prompt shows existing
labels and says "you MAY reuse one, but only if it describes the SAME specific
work". As the taxonomy grows, reuse should become likelier — that is the
mechanism the feature relies on to stay coherent.

Arms:
  COLD  — generic seed only (what drift_control measured)
  WARM  — seed additionally contains one apt, specific label for this work
  HOT   — seed contains the apt label AND several near-miss variants of it,
          which is what a drifted taxonomy actually looks like after a while

Measured: how often the model reuses an existing label vs mints a new one.

KNOWN CONFOUND, stated up front: clients.claude_cli_client shells out to
`claude -p` and CANNOT pass temperature=0 — the library passes it, the CLI
ignores it. Production Hermes calls the API at temperature 0.0. These numbers
therefore describe CLI-default sampling and should be re-run against a
temperature-0 API client before being treated as production figures.

Run: python3 reuse_experiment.py [--n=4]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 4))

USER = ("Our reconciliation job is dropping about 0.3% of settlement rows overnight. "
        "Here's the job config and last night's log tail — figure out where the rows are going.")
ASSISTANT = ("The drop is in the dedupe stage: settlement_id is compared after a lossy cast "
             "to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.")

GENERIC = ["research", "analysis", "code_review", "generation"]
APT = "reconciliation_dedupe_bug"
NEAR_MISSES = [
    "reconciliation_dedupe_bugs",
    "reconcile_dedupe_bug",
    "reconciliation_row_dedupe",
    "settlement_dedupe_bug",
]

ARMS = {
    "COLD": GENERIC,
    "WARM": GENERIC + [APT],
    "HOT": GENERIC + [APT] + NEAR_MISSES,
}


def main():
    t0 = time.time()
    out = {}
    for arm, seed in ARMS.items():
        labels = []
        for _ in range(N):
            clf = lib.Classifier(
                llm=claude_cli_client(),
                taxonomy=lib.InMemoryTaxonomy(seed=list(seed)),
                host="Hermes",
            )
            labels.append(clf.classify_turn(USER, ASSISTANT))
        reused = sum(1 for l in labels if l in seed)
        out[arm] = {
            "seed_size": len(seed),
            "labels": labels,
            "reused": reused,
            "minted_new": N - reused,
            "distinct": len(set(labels)),
        }
        print(f"{arm:<5} seed={len(seed):<2} reused {reused}/{N}  distinct {len(set(labels))}  {labels}")

    print("\ninterpretation")
    print("-" * 62)
    cold, warm, hot = out["COLD"], out["WARM"], out["HOT"]
    print(f"  COLD reuse {cold['reused']}/{N} -> WARM reuse {warm['reused']}/{N} -> HOT reuse {hot['reused']}/{N}")
    if warm["reused"] > cold["reused"]:
        print("  An apt existing label DOES pull the model toward reuse: the prompt's")
        print("  reuse instruction works when a genuinely matching label is present.")
    else:
        print("  An apt existing label did NOT increase reuse. The reuse instruction")
        print("  is not strong enough to stabilize the vocabulary on its own.")
    if hot["reused"] < warm["reused"]:
        print("  Near-miss variants REDUCE reuse — a partly-drifted taxonomy makes the")
        print("  model less willing to pick any of them, so drift compounds itself.")
    print(f"\n  elapsed {time.time()-t0:.0f}s")
    (SPIKE_DIR / "reuse_experiment_result.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
