#!/usr/bin/env python3
"""Does removing the prompt's examples also destroy DESIRABLE reuse?

The 2x2 showed that deleting the five hardcoded "Good examples" takes verbatim
reuse from 5/15 to 0/15 — including seed reuse. That looks like a clean win.

But spike 002 established that reuse is the *cure* for taxonomy drift: with an
apt label already in the vocabulary, the model reused it 8/8 and the vocabulary
converged. That measurement was taken WITH the examples present.

If removing the examples suppresses reuse indiscriminately, the "fix" trades
misclassification for permanent fragmentation — a strictly worse outcome, since
fragmentation is the failure condition PROJECT.md names for the whole feature.

  WARM + examples     (spike 002's original condition — expected high reuse)
  WARM - examples     (the proposed fix — reuse must SURVIVE here)

An apt label is seeded; the correct behavior is to reuse it, not mint a synonym.

Run: python3 apt_reuse_regression.py [--n=5]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SPIKES = REPO / ".planning" / "spikes"
sys.path.insert(0, str(SPIKES / "001-extraction-seam"))
sys.path.insert(0, str(SPIKES / "002-host-fit"))
sys.path.insert(0, str(HERE))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402
from seed_attractor_experiment import build_prompt  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 5))

USER = ("Our reconciliation job is dropping about 0.3% of settlement rows overnight. "
        "Here's the job config and last night's log tail — figure out where the rows are going.")
ASSISTANT = ("The drop is in the dedupe stage: settlement_id is compared after a lossy cast "
             "to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.")

APT = "reconciliation_dedupe_bug"
WARM_SEED = ["research", "analysis", "code_review", "generation", APT]


def classify(prompt: str) -> str:
    call = claude_cli_client()
    resp = call(messages=[
        {"role": "system", "content": "You classify Hermes turns into task_type labels. Output only the label."},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=64, timeout=30.0)
    return lib.validate_label((resp.choices[0].message.content or "").strip())


def main():
    t0, out = time.time(), {}
    for arm, with_examples in (("WARM + examples", True), ("WARM - examples", False)):
        labels = [classify(build_prompt(USER, ASSISTANT, WARM_SEED, with_examples)) for _ in range(N)]
        reused = sum(1 for l in labels if l == APT)
        out[arm] = {"labels": labels, "apt_reuse": reused, "n": N}
        print(f"{arm:<18} apt reuse {reused}/{N}   {labels}")

    a = out["WARM + examples"]["apt_reuse"]
    b = out["WARM - examples"]["apt_reuse"]
    print("\ninterpretation")
    print("-" * 62)
    if b >= a or b >= N * 0.6:
        print(f"  Apt reuse SURVIVES example removal ({a}/{N} -> {b}/{N}).")
        print("  Removing the examples suppresses copying an INAPT string without")
        print("  suppressing reuse of an APT one. The fix is safe: the drift cure")
        print("  (spike 002's convergence mechanism) is preserved.")
    else:
        print(f"  Apt reuse COLLAPSES without the examples ({a}/{N} -> {b}/{N}).")
        print("  Deleting them would trade misclassification for permanent")
        print("  fragmentation — the failure condition PROJECT.md names. The fix")
        print("  must instead make the examples non-copyable (e.g. describe their")
        print("  SHAPE) rather than remove the reuse licence outright.")
    print(f"\n  elapsed {time.time()-t0:.0f}s")
    (HERE / "apt_reuse_result.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
