# Host Integration

How to attach the classification core to a host that is not Hermes — what an adapter must
supply, what it costs, and where classification must sit relative to the request path.

## Requirements

From the `portable-task-classifier` idea in `.planning/spikes/MANIFEST.md`:

- Every host must implement its own **"is this input substantive"** gate. The library
  classifies empty input without complaint.
- **Classify out of band, never on a request's critical path.** Inline classification adds a
  full model round-trip plus a vocabulary fetch to every request, and a classifier calling
  through the proxy it guards can be blocked by the halt rule it is enforcing.
- Exactly four injection points: model client, taxonomy store, logger, host name.

## How to Build It

### What an adapter owes the library

Three things, and nothing else:

1. **Extract** `(user_message, assistant_response)` — and a transcript string if you want job
   inference.
2. **Gate** on substance before calling (see What to Avoid).
3. **Supply identity** — whatever this host has to attribute spend with.

### Measured adapter cost

```
shared library (revenium_classify)    228 lines
LiteLLM guardrail adapter              22 lines    -> 91% shared
Claude Code adapter                    56 lines    -> 80% shared
client shims (both hosts)              26 lines
```

Honest reading: those ratios are "to get a label", not "to run a metering pipeline". Neither
adapter does dedupe, idempotency, marker persistence, or delivery — the parts that make up most
of Hermes' host-bound 76%. A production Claude Code metering host needs most of them back.

### Host A — LiteLLM guardrail (`sources/002-host-fit/hosts/litellm_guardrail.py`)

The hook sees **one** request/response pair: no session history, no session DB, no durable
per-session filesystem. Everything Hermes does to *find* a transcript is inapplicable — it is
simply handed to you. That is why the adapter is 22 lines.

```python
def extract_turn(payload):
    data = payload.get("data") or {}
    user = next((m.get("content") or "" for m in reversed(data.get("messages") or [])
                 if m.get("role") == "user"), "")
    choices = (payload.get("response") or {}).get("choices") or []
    assistant = ((choices[0] or {}).get("message") or {}).get("content") or "" if choices else ""
    return user, assistant
```

Identity available: `metadata.user_api_key_team_id` / `user_id` / `alias`, plus the model. No
session id — so **per-arc job inference is meaningless here** (one request is not an arc), and
the taxonomy has nowhere local to live. Use `InMemoryTaxonomy` backed by a service.

### Host B — Claude Code session transcript (`sources/002-host-fit/hosts/claude_code.py`)

One JSONL per session at `~/.claude/projects/<slug>/<session-uuid>.jsonl`. Record shapes
verified on a real machine (2026-08-15):

*(The shipped fixture reproduces these shapes with synthetic content — see the sources
README. The shapes themselves were observed on a real machine.)*

- `type=user` → `message.content` (str **or** content-block list), `sessionId`, `isSidechain`,
  `uuid`, `parentUuid`, `cwd`, `gitBranch`
- `type=assistant` → `message.content` (block list), `message.usage{input_tokens,
  output_tokens, cache_read_input_tokens, cache_creation_input_tokens}`, `requestId`,
  `isSidechain`
- also present and ignorable: `ai-title`, `last-prompt`, `mode`, `permission-mode`,
  `attachment`, `file-history-snapshot`/`delta`, `system`

Content blocks must be flattened — `text` blocks joined, `tool_use` blocks rendered as
`[tool_use:<name>]`.

This host is a much closer analogue to Hermes than the guardrail: it *has* a session, a
subagent flag (`isSidechain`, the analogue of `parent_session_id`), per-call usage numbers, and
a durable per-session file. Which means it re-poses most of the questions Hermes' host-bound 76%
answers — dedupe, idempotency, where markers live — against different primitives.

### Where classification must sit

**Out of band. Always, unless you are routing on the label rather than billing on it.**

| Path | Added latency to the caller |
|------|-----------------------------|
| Post-hoc (Hermes' model: boundary hook + cron) | **0 ms** |
| Inline (guardrail hook) | one full model round-trip + a vocabulary fetch, per request |

The LiteLLM use case wants the **post-hoc half** of Hermes' design, not the inline half.

### Cost envelope, measured

Per-classification input is **bounded** — the library's 1024-char cap on the labels block binds
from ~100 labels onward:

| Vocabulary size | Prompt bytes | Est. tokens | Truncated |
|-----------------|--------------|-------------|-----------|
| 0 | 1228 | 306 | no |
| 25 | 1742 | 434 | no |
| 100 | 2244 | 560 | **yes** |
| 2000 | 2244 | 560 | yes |

~560 estimated input tokens and a handful of output tokens, regardless of how large the taxonomy
grows. Preserve that cap in any extraction.

Vocabulary-service hop (real loopback HTTP, 50 samples): **p50 0.37 ms, p95 0.69 ms** — a floor,
not a forecast. Same-region realistically 1–20 ms.

## What to Avoid

- **Never let the library see unextracted input.** It will classify two empty strings without
  complaint: it calls the model and returns whatever comes back. A first Claude Code run here
  reported a confident label having parsed **0 turns**, and that silently "passed". Hermes'
  substance gating lives in the host-bound code, so each host must re-implement it. Use
  `assert_extraction_nonempty` from `sources/002-host-fit/run_hosts.py`.
- **Never route the classifier's own model call through the proxy it guards.** The
  classification call becomes customer-visible traffic: metered, and subject to the guardrails
  being enforced — *including the halt rule it may be evaluating*. Under an active halt, the
  classifier can be blocked by the rule it is helping enforce. Give it direct provider
  credentials or an explicit exemption. (Hermes avoids this by construction: its classifier uses
  `agent.auxiliary_client` and enforcement lives in a different process reading a status file.)
- **Do not quote a latency number from the `claude` CLI harness.** Its ~5.2 s process-startup
  floor swamps the measurement — a trivial prompt and a 560-token classification are
  statistically indistinguishable through it (delta(min) `+0.02s`, delta(median) `−1.62s`,
  distributions overlapping). The first attempt reported classification as *faster* than an
  `ok` prompt, an ordering artifact. Measure with a direct API client at temperature 0.
- **Do not assume the client contract is universal.** It is OpenAI-shaped (`messages=`,
  `temperature=`, `max_tokens=`, `timeout=`; result read as `.choices[0].message.content`),
  inherited from Hermes' auxiliary client. Other clients need a ~25-line shim.

## Constraints

- Job/arc inference requires a session concept. A guardrail has none — turn-level `task_type`
  only.
- The guardrail has no durable per-session filesystem; `FileTaxonomy` is inapplicable there.
- Claude Code transcript content may be a string *or* a content-block list; handle both.
- The recursion hazard is an architectural argument verified against the hook contract, not an
  experiment against a running LiteLLM proxy.

## Origin

Synthesized from spikes: 002 (host-fit, VALIDATED), 004 (inline-latency, PARTIAL)
Source files: `sources/002-host-fit/`, `sources/004-inline-latency/`
Runnable demo: `sources/002-host-fit/serve_demo.py` (one input, three host framings, port 8722)
