#!/usr/bin/env python3
"""Can classification live on a guardrail's critical path?

Hermes classifies POST-HOC: the plugin fires at session end / turn end and the
cron ships markers a minute later. Nothing waits. A LiteLLM guardrail is the
opposite — an `async_pre_call_hook` / `async_post_call_success_hook` runs while
the caller's request is in flight, so anything it does is added latency for a
paying user.

Measured here:
  1. PROMPT SIZE — exact bytes and estimated tokens of the classification prompt,
     including how it grows as the vocabulary grows (the library caps the labels
     block at 1024 chars; this verifies the cap actually binds).
  2. WALL CLOCK — baseline CLI round-trip vs a real classification round-trip.
     CONFOUND: the `claude -p` client carries CLI startup overhead a direct API
     call would not. Reported as (classification - baseline) to subtract most of it.
  3. SERVICE HOP — if the vocabulary becomes a service (spike 002/003's
     conclusion), the guardrail also pays a network round-trip per classification.
     Measured against a real local HTTP server, which is a floor, not an estimate.
  4. RECURSION — whether classifying traffic inside a proxy generates traffic
     through that same proxy.

Run: python3 measure.py [--n=5]
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
sys.path.insert(0, str(SPIKE_DIR.parent / "001-extraction-seam"))
sys.path.insert(0, str(SPIKE_DIR.parent / "002-host-fit"))

import revenium_classify as lib  # noqa: E402
from clients import claude_cli_client  # noqa: E402

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 5))

USER = ("Our reconciliation job is dropping about 0.3% of settlement rows overnight. "
        "Here's the job config and last night's log tail — figure out where the rows are going.")
ASSISTANT = ("The drop is in the dedupe stage: settlement_id is compared after a lossy cast "
             "to int64, so ids above 2^53 collide and the second row is discarded as a duplicate.")

# ~4 chars/token is the standard rough estimate; good enough for an order-of-magnitude
# cost figure, and stated as an estimate rather than a measurement.
CHARS_PER_TOKEN = 4


def prompt_growth():
    """How big is the classification prompt, and does the 1024-char cap bind?"""
    rows = []
    for vocab_size in (0, 4, 25, 100, 500, 2000):
        labels = [f"some_label_number_{i}" for i in range(vocab_size)]
        p = lib.build_classification_prompt(USER, ASSISTANT, labels)
        rows.append({
            "vocab_size": vocab_size,
            "prompt_bytes": len(p.encode("utf-8")),
            "est_tokens": len(p) // CHARS_PER_TOKEN,
            "truncated": "[truncated]" in p,
        })
    return rows


def wall_clock():
    """Baseline CLI round-trip vs a real classification round-trip."""
    base, clf_times = [], []
    for _ in range(N):
        t0 = time.time()
        subprocess.run(["claude", "-p", "ok"], capture_output=True, text=True, timeout=60)
        base.append(time.time() - t0)
    clf = lib.Classifier(llm=claude_cli_client(),
                         taxonomy=lib.InMemoryTaxonomy(seed=["research", "analysis"]),
                         host="LiteLLM proxy")
    for _ in range(N):
        t0 = time.time()
        clf.classify_turn(USER, ASSISTANT)
        clf_times.append(time.time() - t0)
    return base, clf_times


class _TaxHandler(BaseHTTPRequestHandler):
    VOCAB = json.dumps({"labels": [f"label_{i}" for i in range(200)]}).encode()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.VOCAB)))
        self.end_headers()
        self.wfile.write(self.VOCAB)

    def log_message(self, *a):
        pass


def service_hop(samples=50):
    """Floor cost of a vocabulary-service round trip, measured on loopback."""
    srv = HTTPServer(("127.0.0.1", 8733), _TaxHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    times = []
    try:
        for _ in range(samples):
            t0 = time.time()
            urllib.request.urlopen("http://127.0.0.1:8733/vocab", timeout=5).read()
            times.append((time.time() - t0) * 1000)
    finally:
        srv.shutdown()
    return times


def main():
    print("1. PROMPT SIZE vs VOCABULARY SIZE")
    print("-" * 66)
    print(f"   {'vocab':>6}  {'bytes':>7}  {'est tokens':>10}  truncated")
    growth = prompt_growth()
    for r in growth:
        print(f"   {r['vocab_size']:>6}  {r['prompt_bytes']:>7}  {r['est_tokens']:>10}  {r['truncated']}")
    capped = [r for r in growth if r["truncated"]]
    print(f"   => the 1024-char labels cap binds from vocab "
          f"{capped[0]['vocab_size'] if capped else 'n/a'} onward; prompt size is BOUNDED "
          f"at ~{max(r['prompt_bytes'] for r in growth)} bytes regardless of vocabulary growth.")

    print("\n2. WALL CLOCK (claude CLI client — includes CLI startup overhead)")
    print("-" * 66)
    base, clf = wall_clock()
    b_med, c_med = statistics.median(base), statistics.median(clf)
    print(f"   baseline 'ok' round-trip   n={N}  median {b_med:.2f}s  "
          f"min {min(base):.2f}  max {max(base):.2f}")
    print(f"   classification round-trip  n={N}  median {c_med:.2f}s  "
          f"min {min(clf):.2f}  max {max(clf):.2f}")
    print(f"   => classification adds ~{c_med - b_med:+.2f}s over the baseline call.")
    print("      Both include CLI startup; the DELTA is the closer estimate of")
    print("      real added inference latency, and it is still not an API measurement.")

    print("\n3. VOCABULARY SERVICE HOP (loopback floor, not a WAN number)")
    print("-" * 66)
    hop = service_hop()
    hop.sort()
    print(f"   n={len(hop)}  p50 {statistics.median(hop):.2f}ms  "
          f"p95 {hop[int(len(hop)*0.95)]:.2f}ms  max {max(hop):.2f}ms")
    print("   => a same-region service call realistically lands 1-20ms; cross-region")
    print("      or cold-start serverless is far worse. This is the FLOOR.")

    print("\n4. RECURSION CHECK")
    print("-" * 66)
    print("   A guardrail running inside the proxy that classifies traffic must itself")
    print("   call a model. If that call is routed through the same proxy, it is")
    print("   metered as customer traffic and is itself subject to guardrails —")
    print("   including the halt rule it may be enforcing. The classification client")
    print("   MUST bypass the proxy (direct provider credentials) or be explicitly")
    print("   exempted, or the system can deadlock itself under a halt.")

    print("\nVERDICT INPUTS")
    print("-" * 66)
    print(f"   inline classification adds one full model round-trip (~{c_med-b_med:.1f}s here,")
    print("   optimistically several hundred ms against a small fast model via API)")
    print("   plus a vocabulary fetch, to EVERY request the guardrail sees.")
    print("   Post-hoc classification (Hermes' model) adds exactly 0ms to the caller.")

    (SPIKE_DIR / "measure_result.json").write_text(json.dumps({
        "prompt_growth": growth,
        "baseline_s": base, "classification_s": clf,
        "delta_median_s": round(c_med - b_med, 2),
        "service_hop_ms": {"p50": statistics.median(hop), "p95": hop[int(len(hop)*0.95)]},
    }, indent=2))


if __name__ == "__main__":
    main()
