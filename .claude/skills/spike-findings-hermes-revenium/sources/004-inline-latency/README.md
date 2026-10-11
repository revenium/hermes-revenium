---
spike: 004
idea: portable-task-classifier
name: inline-latency
type: standard
validates: "Given classification on a guardrail's critical path, when run against realistic payloads, then measure the added latency and cost versus the post-hoc path"
verdict: PARTIAL
related: [002-host-fit, 003-taxonomy-drift]
tags: [latency, cost, architecture, guardrail]
---

# Spike 004: Inline Latency

## What This Validates

Hermes classifies **post-hoc**: the plugin fires at a session/turn boundary and the cron ships
markers a minute later. Nobody waits. A LiteLLM guardrail runs inline: an
`async_pre_call_hook` / `async_post_call_success_hook` runs while a paying caller's request is
in flight. Anything the guardrail does is latency that customer pays for.

**Given** classification running on a guardrail's critical path, **when** exercised with
realistic payloads, **then** what does it actually cost in latency, tokens and
architectural hazards?

## How to Run

```bash
cd .planning/spikes/004-inline-latency
python3 measure.py --n=5               # prompt growth, wall clock, service hop, recursion
python3 wall_clock_interleaved.py --n=6  # the corrected timing attempt
```

## Investigation Trail

**1. Prompt size is bounded.**

| Vocabulary size | Prompt bytes | Est. tokens | Labels block truncated |
|-----------------|--------------|-------------|------------------------|
| 0 | 1228 | 306 | no |
| 4 | 1286 | 320 | no |
| 25 | 1742 | 434 | no |
| 100 | 2244 | 560 | **yes** |
| 500 | 2244 | 560 | yes |
| 2000 | 2244 | 560 | yes |

The library's 1024-character cap on the labels block binds from roughly 100 labels onward, so
**the classification prompt is bounded at ~2.2 KB / ~560 estimated tokens no matter how large
the taxonomy grows.** Per-classification input cost is therefore predictable and does not
degrade as the vocabulary matures. Output is a single label, a handful of tokens.

Preserve this cap in any extraction.

**2. The first wall-clock attempt produced a nonsense result, and I kept it in the record.**
It reported classification as **0.64s faster** than a two-token `ok` prompt. Cause: all
baseline calls ran first and absorbed the cold start (baseline max 16.1s against a 5.2s floor).
An ordering artifact reported as a measurement.

**3. Rebuilt it interleaved with a discarded warm-up; the harness still cannot measure the added latency.**

```
  pair 1: baseline 7.09s  classification 5.53s
  pair 2: baseline 7.01s  classification 6.35s
  pair 3: baseline 7.98s  classification 5.36s
  pair 4: baseline 5.13s  classification 5.15s
  pair 5: baseline 5.79s  classification 5.21s
  pair 6: baseline 6.86s  classification 5.27s

  baseline        min 5.13  median 6.93  max 7.98
  classification  min 5.15  median 5.31  max 6.35
  delta (min) +0.02s   delta (median) -1.62s   distributions OVERLAP
```

A trivial prompt and a 560-token classification are indistinguishable through this harness;
the `claude` CLI's ~5.2s process-startup-and-auth floor dominates completely, and the median
delta is still negative. **No latency number from this instrument is worth quoting.** Getting
the real figure requires a direct API client with `temperature=0`, which this environment has
no key for.

**4. The vocabulary-service hop, measured rather than guessed.** A real loopback HTTP server,
50 samples: **p50 0.37ms, p95 0.69ms, max 14.5ms.** That is a lower bound, not a forecast; it
measures serialization and the local socket, nothing else. A same-region service call
realistically lands in the 1–20ms band; cross-region or a cold serverless instance is far
worse. Useful as the lower bound on what spike 003's "shared vocabulary" recommendation costs
a guardrail per request.

**5. The recursion hazard required no measurement.** A guardrail
running *inside* the proxy, classifying the traffic passing through it, must itself call a
model. If that call is routed through the same proxy it becomes customer-visible traffic: it
is metered, and it is subject to the guardrails being enforced, **including the halt rule it
may be evaluating.** Under an active halt, a classifier that depends on the proxy can be
blocked by the very rule it is helping enforce. The classification client must hold direct
provider credentials or be explicitly exempted from enforcement.

Hermes does not have this problem, because its classifier calls `agent.auxiliary_client` and
its enforcement lives in a different process reading a status file.

## Results

**Verdict: PARTIAL.** Three of the four sub-questions are answered; the added inference
latency is not measurable with the tooling available here.

**Answered:**

- **Token cost is bounded and predictable**: ~560 estimated input tokens per classification
  regardless of vocabulary size, one label out. The 1024-char cap enforces this bound.
- **A vocabulary service adds a measurable hop**: 0.37ms p50 on loopback as the floor,
  realistically 1–20ms same-region, per classification.
- **Inline classification inside a proxy has a recursion hazard** that can deadlock under an
  active halt unless the classification client bypasses the proxy.

**Not answered:** the actual added latency of the inference itself. Needs a direct API client
at temperature 0. The architecture still establishes the request-path cost:

> Inline classification adds **a full extra model round-trip to every request the guardrail
> sees**, whatever that round-trip costs on the chosen model. Post-hoc classification adds
> exactly **0ms** to the caller.

**Recommendation:** do not classify inline. The guardrail should capture what it needs and
classify out of band, which is precisely the architecture Hermes already uses, and it means
the LiteLLM use case wants the *post-hoc* half of this design, not the inline half. If inline
classification is required anyway (e.g. to *route* on the label rather than to bill on it),
budget a full model round-trip plus a vocabulary fetch per request, and give the classifier
credentials that bypass the proxy.

### Limits

- The `claude` CLI harness cannot measure inference latency, cannot pass `temperature=0` and
  carries a ~5.2s startup floor. Every timing statement above is bounded by that.
- The service hop is loopback-only. It bounds the cost from below and says nothing about a
  real deployment.
- The recursion hazard is an architectural argument verified by reading the hook contract, not
  an experiment against a running LiteLLM proxy.
