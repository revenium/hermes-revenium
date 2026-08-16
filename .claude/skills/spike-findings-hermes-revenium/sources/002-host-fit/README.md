---
spike: 002
idea: portable-task-classifier
name: host-fit
type: standard
validates: "Given the extracted core, when driven by a LiteLLM-guardrail payload and a Claude Code session JSONL, then both classify with no Hermes import"
verdict: VALIDATED
related: [001-extraction-seam]
tags: [portability, litellm, claude-code, taxonomy, drift]
---

# Spike 002: Host Fit

## What This Validates

**Given** the `revenium_classify` core extracted in spike 001, **when** it is driven by two
hosts with completely different session models — a LiteLLM guardrail (one request/response, no
session, no filesystem, on the critical path) and a Claude Code session transcript (JSONL,
subagent flag, per-call usage) — **then** both classify real content with no Hermes import.

## Research

Both host shapes were taken from reality, not invented:

- **Claude Code**: record types observed in `~/.claude/projects/<slug>/<uuid>.jsonl` on this
  machine — `user` / `assistant` carry `message.content` (string or content-block list) plus
  `message.usage{input_tokens, output_tokens, cache_read_input_tokens,
  cache_creation_input_tokens}`, `sessionId`, `isSidechain` (the analogue of Hermes'
  `parent_session_id`), `parentUuid`. Also present: `ai-title`, `last-prompt`, `mode`,
  `attachment`, `file-history-snapshot/delta`, `system`.
- **LiteLLM guardrail**: the `CustomGuardrail` hook shape — a `data` dict (model, messages,
  metadata with `user_api_key_team_id` / `user_id` / `alias`) plus the response.

**Model client:** rather than stub the LLM, the host adapters inject the local `claude` CLI as
a real client (`clients.claude_cli_client`). A stub would have begged the question the spike
asks. See the confound note under Results.

## How to Run

```bash
cd .planning/spikes/002-host-fit

python3 run_hosts.py               # both hosts, real model calls (~17s)
python3 run_hosts.py --scripted    # deterministic, no model call
python3 drift_control.py --n=3     # control vs treatment on label stability (~70s)
python3 reuse_experiment.py --n=4  # does taxonomy reuse dampen drift? (~70s)
python3 serve_demo.py              # UI at http://localhost:8722 — one input, three host framings
```

## What to Expect

- `run_hosts.py` → a JSON block with a plausible `task_type` per host, `no-Hermes assertion: PASS`,
  and the adapter-cost table.
- `drift_control.py` → whether identical prompts reproduce a label.
- `reuse_experiment.py` → `COLD reuse 0/4 -> WARM reuse 4/4 -> HOT reuse 4/4`.
- `serve_demo.py` → three columns; the banner turns red when the hosts disagree.

## Observability

`serve_demo.py` keeps an in-process event log (one record per classification with host, label,
elapsed, prompt bytes; one per comparison with the distinct-label count) exportable at
`GET /log`. `drift_control.py` and `reuse_experiment.py` each write their raw arms to
`*_result.json` so the numbers below can be re-derived rather than trusted.

## Investigation Trail

**1. Both hosts classify real content.** With a real model call:

| Host | Input | Label | Elapsed |
|------|-------|-------|---------|
| LiteLLM guardrail | synthetic settlement-reconciliation payload | `sql_row_dedupe_bug` | 8.25s |
| Claude Code | a real 19-turn session from `~/.claude/projects/` | `github_account_switching` | 8.35s |

Both apt. `assert_no_hermes()` passes: no `classifier` module, nothing imported from a
`.hermes` tree.

**2. The first Claude Code run silently classified nothing.** It reported a confident label
while having parsed **0 turns** — my fixture had been pre-normalized into a shape the adapter
didn't read. The library will happily classify two empty strings; it calls the model and
returns whatever comes back. Hermes' "is this turn substantive" gating lives in the host-bound
76%, so **every new host must re-implement that guard or burn inferences on empty input.**
`assert_extraction_nonempty` now exists precisely because this failure mode passed.

**3. Adapter cost — the real answer to "what does the other 76% cost each host":**

```
shared library (revenium_classify)    228 lines
LiteLLM guardrail adapter              22
Claude Code adapter                    56
client shims (both hosts)              26
reuse: LiteLLM 91% shared · Claude Code 80% shared
```

Honest caveat: those ratios are "to get a label", not "to run a metering pipeline". Neither
adapter does dedupe, idempotency, marker persistence, or delivery — the parts that make up most
of Hermes' 76%. A production Claude Code metering host would need most of them back.

**4. The demo showed three hosts disagreeing — so I ran the control.** Same input, same
library, same model, only the `host` word differing: `sql_query_debug` /
`settlement_id_int64_overflow` / `reconciliation_row_dedupe_bug`. Tempting to conclude that
host framing fragments the taxonomy. **The control refuted that**: the same host word, three
times, produced three different labels too. 11 distinct labels from 12 classifications of one
piece of work. Framing wasn't the cause; free-form minting was.

**5. But the control's seed was not the production dynamic.** Production classifies against a
*grown* taxonomy whose prompt invites reuse. Re-ran with three seeds:

| Arm | Seed | Reuse | Distinct |
|-----|------|-------|----------|
| COLD | 4 generic labels | 0/4 | 4 |
| WARM | + 1 apt label (`reconciliation_dedupe_bug`) | **4/4** | **1** |
| HOT | + apt label and 4 near-miss variants | **4/4** (chose the apt one) | **1** |

Once an apt label exists, convergence is total — 8/8 across WARM and HOT — and near-miss
variants did not confuse it.

## Results

**Verdict: VALIDATED.** Both hosts drive the extracted core with no Hermes import, on real
content, with a real model. The adapters are 22 and 56 lines against a 228-line shared core.

**The finding that matters is not the one the spike set out to get.**

Drift is a **cold-start** property, not an intrinsic one. An empty or generic vocabulary
produces near-total fragmentation (0/4 reuse, 4 distinct labels for one piece of work); a
vocabulary containing one apt label produces total convergence (8/8 reuse), even when
salted with confusable near-misses.

That relocates the whole question:

- **Sharing the code is cheap, safe, and mildly useful.** Spike 001 proved it is
  behavior-preserving; this spike proves 80–91% reuse to get a label.
- **Sharing the *vocabulary* is the thing that actually protects the product.** Three hosts
  each starting from their own cold taxonomy will each fragment independently through their
  cold-start window, and converge on *different* attractors for the same work. A shared library
  with per-host taxonomy files does not fix this. A shared taxonomy — served, not filed — does.

So the answer to "should we extract a generic Python library?" is: yes, but that is the smaller
half. The library is ~250 lines of prompt-and-validation glue. **The asset is the taxonomy**,
and it wants to be a service with a client, not a JSON file per host.

### Confounds and limits — read before quoting these numbers

- **Temperature.** `claude_cli_client` shells out to `claude -p` and cannot pass
  `temperature=0`; the library passes it and the CLI ignores it. Production Hermes calls the
  API at temperature 0.0. These are CLI-default-sampling numbers. Expect real temp-0 COLD drift
  to be lower — which would soften the COLD result but leave the WARM/HOT convergence, the
  load-bearing half, intact.
- **Scale.** One piece of work, one model, N=3–4 per arm. Enough to establish direction, not
  to quote a drift rate.
- **The HOT arm was not adversarial.** Its near-misses were all clearly worse than the apt
  label. A harder test would offer two equally defensible labels.
- **Both fixtures are synthetic** (shape-accurate, hand-written). The Claude Code *record
  shapes* were captured from a real session on 2026-08-15 and the fixture reproduces them
  field-for-field, but the transcript content was regenerated: the original capture carried a
  developer email, home paths, GitHub account names and token scopes that nothing in the
  adapter reads (Greptile P2 on PR #42; no live credentials — `gh` had already masked the token
  values). The replacement also adds `isSidechain` turns, which the real capture happened not
  to contain, so the subagent path is exercised rather than merely present.
- **The measured run below used the original real transcript**, hence `github_account_switching`
  as its label and the 19-turn / 0-subagent counts. Re-running against the synthetic fixture
  gives 8 turns / 2 subagent turns and a different label; the adapter behavior is unchanged.
