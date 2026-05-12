# Feature Research

**Domain:** AI cost-metering / LLM observability — task-type classification on metered completions
**Researched:** 2026-05-12
**Confidence:** HIGH for product behavior (verified against vendor docs); MEDIUM for "differentiator" claims (no competitor was observed shipping the specific combination this project proposes)

## Scope

This research focuses on a single dimension of LLM observability: **how products attach a "what was the agent doing?" label to metered completions**. It deliberately ignores adjacent capabilities (evals, prompt management, replay, A/B testing) that are validated as out of scope in `PROJECT.md`.

The Revenium `meter completion` endpoint is the wire protocol this skill targets. Its accepted fields were verified directly against the API reference: `task_type` is **free-form text** with example values (`'chat'`, `'summarization'`, `'code-generation'`, ...), while `operation_type` is a **controlled enum**: `CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER, TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO, VIDEO, IMAGE`. This is the contract every feature below has to fit through.

## What Competing Products Actually Ship

Before categorizing, here is the verified competitive landscape for the four research questions.

### Q1 / Q2: Who supports task-type tagging and how is the label produced?

| Product | What they call it | How the label is produced | Free-form vs enum |
|---------|-------------------|---------------------------|-------------------|
| **Helicone** | `Helicone-Property-<Name>` HTTP headers; `Helicone-Session-Id` / `-Path` / `-Name` for grouping | User-defined per request; SDK passes headers. `Helicone-User-Id` is the only reserved property. | Free-form, no enforcement |
| **Langfuse** | `tags` (list of strings, max 200 chars each), `metadata` (k/v), `observationType` | SDK-instrumented; agent code calls `trace.update(tags=[...])` or uses `propagate_attributes()` to apply to a subtree | Tags are free-form strings; `observationType` is a fixed enum: `event`, `span`, `generation`, `agent`, `tool` |
| **LangSmith** | `run_type` + `tags` + `metadata` | SDK-instrumented via `@traceable(run_type=...)` decorator or `trace` context manager; can be set statically or dynamically | `run_type` is fixed-ish (`llm`, `chain`, `tool`, ...) — some features are LLM-only; tags free-form |
| **OpenLLMetry / Traceloop** | `traceloop.span.kind` ∈ `{workflow, task, agent, tool}`; `traceloop.workflow.name`, `traceloop.entity.name`, `traceloop.association.properties` | SDK-instrumented via decorators (`@workflow`, `@task`, `@agent`, `@tool`); name is developer-supplied | Span kind is a fixed enum of 4; workflow/entity names are free-form |
| **Arize Phoenix / OpenInference** | `openinference.span.kind` (required), `tag.tags` (List[str]) | SDK-instrumented; span kind is set when the span is created | Span kind is a **fixed enum of 10**: `LLM, EMBEDDING, CHAIN, RETRIEVER, RERANKER, TOOL, AGENT, GUARDRAIL, EVALUATOR, PROMPT`. `tag.tags` is free-form |
| **Braintrust** | `span_type`, tags, metadata | SDK-instrumented via `@traced` decorator and span context | Span types are conceptual (tool / reasoning / state transition / LLM) per docs; tags free-form |
| **Portkey** | `metadata` k/v pairs (128 char max per value); special `_user`; recommended fields like `feature`, `team`, `env` | Gateway-level: client sets metadata on the request; gateway captures it. Required fields can be defined per workspace. | Free-form values; recommended (not enforced) keys |
| **Datadog LLM Observability** | `span_kind` ∈ `{LLM, workflow, agent, tool, task, embedding, retrieval}` + tags + metadata | SDK-instrumented (`ddtrace.llmobs`) — `task` is the kind for non-external standalone steps | Span kind is a fixed enum of 7; tags free-form |
| **OpenTelemetry GenAI semconv** | `gen_ai.operation.name` (string with well-known values: `inference`, `retrieval`, `create_agent`, `invoke_agent`, ...) | Auto-instrumented by SDK based on call site | Conditionally-required well-known list — custom values allowed if no predefined applies |
| **Revenium** | `task_type` (free-form) + `operation_type` (enum of 17) | Currently in the existing Hermes skill: **not produced at all** (today's gap). Other Revenium integrations derive `operation_type` from system logs (CHAT vs TOOL_CALL vs GUARDRAIL) | Controlled `operation_type`; free-form `task_type` |

**Production-mode pattern.** Every product surveyed gets the label one of three ways:
1. **SDK-instrumented at the call site** (LangSmith, OpenLLMetry, Phoenix, Braintrust, Datadog, OTel) — the developer writes `run_type="retriever"` once in code and the tag follows the call. This is the dominant pattern.
2. **HTTP header / gateway-level** (Helicone, Portkey) — the calling app stamps a header; the gateway records it. Equivalent semantically to SDK instrumentation, just at a different layer.
3. **System-derived from logs** (other Revenium integrations) — a background process reads structured session logs and infers the operation type after the fact.

**Nobody surveyed ships agent-self-classification as a first-class product feature.** The closest analog is LLM-as-judge classification *of someone else's traces* (research/eval pattern), which is the inverse of what this project does. Hermes-Revenium proposing agent-self-classification post-turn, with the cron splitting cost across markers, appears to be a genuinely novel attribution mechanism within this design space. (MEDIUM confidence — verified absence is hard to prove, but the surveyed docs are consistent.)

### Q3: Controlled vocabulary / taxonomy enforcement

| Layer | Who enforces | What's enforced |
|-------|--------------|-----------------|
| Span kind / observation type | Every observability product surveyed | Fixed enum of 4–10 values (the "kind" axis). This is the closest analog to a controlled vocabulary in the industry. |
| Operation name | OTel GenAI semconv | Conditionally-required well-known list; system-specific custom values allowed when no predefined applies. **This is the only enforcement mechanism shipped at the spec level.** |
| Operation type | Revenium | Hard enum of 17 — server rejects unknowns (inferred from "enum" designation in API ref). |
| Tags / metadata | **No product surveyed** | Free-form. Documentation across the board demonstrates *value patterns* (e.g. Portkey's `feature`, `team`, `env`) but does not enforce a vocabulary. |
| Required metadata fields | Portkey (workspace-level), some others | Existence of certain keys can be required; values are still free-form. |

**Net finding.** The industry has solved "what kind of span is this?" via fixed-enum span kinds. **It has not solved "what activity is this?" via any enforced vocabulary.** Tags and metadata fragmenting across spellings (the exact problem `PROJECT.md` calls out: `code_review` vs `code-review` vs `review_code`) is an unsolved problem in shipped products. (HIGH confidence — verified across Helicone, Langfuse, Portkey, OpenInference docs; all describe values as free-form.)

### Q5: GUARDRAIL / classification-overhead accounting

| Product | GUARDRAIL handling | Cost-of-classification handling |
|---------|--------------------|----|
| OpenInference / Phoenix | Defines `GUARDRAIL` as a span kind; no special cost relationship (cost attrs `llm.cost.*` apply to LLM spans only) | Not addressed — guardrail span exists, but its cost is whatever the LLM call inside it costs |
| Revenium | `GUARDRAIL` is a value in the `operation_type` enum | Other Revenium integrations tag budget-enforcement-resumption-prompt tokens as `GUARDRAIL` so they are visible separately. No automatic split of "the agent's own classification call" because nothing else asks the agent to self-classify. |
| All others | None ship a dedicated guardrail-cost-vs-work-cost split | Not addressed |

**Net finding.** `GUARDRAIL` as a *category label* exists in two places (OpenInference span kinds, Revenium operation_type enum). **No product surveyed automatically separates "tokens spent on classification" from "tokens spent on the underlying work"** — because no product surveyed asks the agent to classify in the first place. This is wide-open differentiating territory. (HIGH confidence.)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist in 2026 once you claim "task-type metering." Missing any of these makes the feature feel incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-completion task_type label on the wire | Every surveyed product (Helicone, Langfuse, LangSmith, Portkey, Phoenix, Datadog, Braintrust, OTel GenAI) supports some form of this; Revenium's API accepts it. Shipping metering without it in 2026 is the gap that triggered this project. | LOW | Already populated as `unclassified` for backward compat; populated from markers when available. Wire field already defined by Revenium. |
| Per-completion operation_type from a controlled enum | Revenium API requires it as an enum; OpenInference span kinds, Datadog span kinds, OpenLLMetry span kinds all enforce one. Free-form here would be a regression vs the surveyed industry baseline. | LOW | Revenium gives us the enum; agent picks from `{CHAT, TOOL_CALL, GUARDRAIL, ...}` via the marker. |
| Backward compatibility — sessions without classification still meter | All surveyed products allow unlabeled traces and aggregate them into a default bucket. Helicone/Langfuse/Portkey simply leave tags absent; the cost still attributes to the request. Breaking existing installs is unacceptable. | LOW | Validated in `PROJECT.md` as `--task-type unclassified` fallback. |
| Idempotent attribution across cron retries | The existing Hermes-Revenium skill already guarantees this for un-split deltas via the `HERMES:<sid>:<total_tokens>` ledger. Once we split across markers, users expect the same guarantee per (session, marker) pair. | MEDIUM | Ledger key extension: `HERMES:<sid>:<total_tokens>:<marker_idx>` or similar. Load-bearing invariant per `PROJECT.md` "Constraints". |
| A "default / unclassified" bucket on the dashboard side | Every product has one — Portkey docs explicitly recommend filling missing dimensions; Langfuse aggregates untagged traces; Helicone shows requests without custom properties under "no value". Users need somewhere for unaccounted spend to land. | LOW | Achieved by always sending `--task-type unclassified` rather than omitting the flag, so Revenium's groupby has a non-null bucket. |
| Free-form task names with examples (not a hardcoded global list) | Revenium's own API designs `task_type` as free-form with examples. Helicone/Langfuse/Portkey all do this. A globally-enforced enum across all installs would be too rigid — different teams classify differently. | LOW | Per-host `task-taxonomy.json` is the right granularity. |
| Tag normalization — case, separators, whitespace | This is the exact failure mode `PROJECT.md` Core Value calls out (`code_review` vs `code-review`). Without it, the "consistently-spelled" promise is broken. | MEDIUM | Lowercase + snake_case normalization on read/write of taxonomy and marker entries. |
| Distinction between "what kind of call" and "what activity" | Every observability product splits these into two axes (kind/type + tags). Conflating them loses analytical power: `task_type=code_review` with `operation_type=GUARDRAIL` is the classifier checking a code-review session; with `operation_type=CHAT` it's the code review itself. | LOW | Already in the design: separate `--task-type` and `--operation-type` flags per marker. |

### Differentiators (Competitive Advantage)

Features that — based on the survey — would set this design apart. The contention here is grounded in what was **not found** in surveyed products. Each row notes confidence.

| Feature | Value Proposition | Complexity | Notes / Confidence |
|---------|-------------------|------------|-------------------|
| **Agent-managed local taxonomy file with strict lookup-first reuse** | No surveyed product ships taxonomy enforcement for free-form labels. Helicone, Langfuse, Portkey, and Datadog all leave tag/metadata vocabulary entirely to the developer. A local `task-taxonomy.json` that the agent reads-before-writing is the simplest mechanism to prevent the `code_review` / `code-review` fragmentation that motivates this project. | MEDIUM | Differentiator within the per-host attribution layer. (MEDIUM confidence — absence of competitor feature verified; whether users care enough to pay for it is unverified.) |
| **Agent-as-classifier (post-turn self-tagging) instead of SDK-instrumented or system-derived** | Surveyed products use SDK call-site decorators (LangSmith, OpenLLMetry, Phoenix), HTTP headers (Helicone, Portkey), or server-side log parsing in other Revenium integrations. Hermes-Revenium's design — the agent classifies what *it* did after it did it, in a context-aware way the SDK or the logs cannot reach — is structurally different and well-matched to the Hermes constraint (no per-turn token data in `state.db`). | MEDIUM | Differentiator at the architectural level. The risk is that LLM self-classification is unreliable; the mitigation is the controlled taxonomy. (HIGH confidence on novelty; MEDIUM on user value — depends on classification accuracy in practice.) |
| **GUARDRAIL accounting for self-classification overhead** | Revenium already buckets budget-check tokens as `GUARDRAIL` in other integrations; OpenInference defines `GUARDRAIL` as a span kind. **Nobody surveyed separates "tokens spent classifying the work" from "tokens spent doing the work"** — because nobody else asks the agent to classify. Doing so here lets us measure the cost of the feature itself, which is unique. | MEDIUM | Strong differentiator. Maps cleanly to the existing Revenium enum value. Sets a precedent for honest overhead accounting. (HIGH confidence — verified absence across all surveyed products.) |
| **Equal-split-across-markers (S2) attribution as a documented approximation** | All surveyed products attribute tokens at the call site — they don't have an attribution problem because they instrument synchronously. This project's attribution problem (`state.db` exposes only session cumulative totals) is unique to Hermes; documenting the equal-split approximation as an explicit, bounded approximation rather than hiding it is honest and differentiating. | LOW | Differentiator only insofar as we're transparent about the imprecision. (HIGH confidence.) |
| **Two-half coupling stays file-based** | Industry pattern is SDK-in-process or HTTP gateway. Files-on-disk-as-contract is unusual but is the right call given the cron model. Documenting this as a deliberate choice (not a workaround) inverts what looks like a limitation into a property: the two halves can be developed, tested, and audited independently. | LOW | This is already a project property; the differentiator is calling it out. (HIGH confidence.) |
| **`adjacent flag wins`** — `--agent`, `--trace-id` carry richer values | The existing skill hardcodes `--agent "Hermes"` and `--trace-id "${sid}"`. Filling those in from marker context (e.g. `--agent` = the specific Hermes role/persona; `--trace-id` = a turn-scoped ID) gives Revenium more axes to group by without enlarging the contract. | LOW | Adjacent improvement; not central but high-leverage. Listed in `PROJECT.md` Active. (HIGH confidence.) |

### Anti-Features (Commonly Requested, Often Problematic)

Things that competitors do or that users might ask for, but this project should deliberately reject. Most are confirmed out-of-scope in `PROJECT.md`; the rest are derived from the survey.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Real-time / synchronous metering from inside the agent's turn** | "Wait, why is there a 60-second lag?" — Helicone/Portkey/Langfuse all meter in-band per request and feel real-time. | Synchronous network calls from inside Hermes turns add latency, failure modes, and break the existing cron architecture. Explicitly out of scope in `PROJECT.md`. | Accept per-cron-cycle attribution (worst case ~60s lag); the cron model is load-bearing. |
| **LLM-as-judge auto-classification of historical traces** | Some products (Langfuse, Braintrust) ship eval pipelines that label traces after the fact. Tempting for backfill. | Duplicates the agent's own knowledge (the agent *just did the work* — it knows better than a post-hoc classifier); doubles guardrail spend; mis-classifies edge cases the agent could have flagged. | Forward-only agent self-classification; explicitly no backfill (`PROJECT.md` Out of Scope). |
| **Server-side taxonomy curation / global label dictionary** | "Wouldn't it be nice if Revenium normalized labels across all my installs?" | Cross-host normalization is Revenium's product surface, not this skill's. Coupling the skill to a server-side dictionary would make the skill non-portable and force a network round-trip into the cron. | Local per-host `task-taxonomy.json`; how Revenium chooses to surface or normalize labels is its concern (`PROJECT.md` Out of Scope). |
| **Per-turn token exactness (S3 weighted, S4 estimator)** | "Equal split is wrong — a 5-token ack and a 5000-token refactor get the same attribution." | True, but unfixable from inside the skill given `state.db` only exposes per-session cumulative totals. S3/S4 add complexity (markers carrying length hints; second-pass estimation) for marginal accuracy gains at our volume. | Equal split (S2); revisit only if observed Revenium-side drift demands it (`PROJECT.md` Out of Scope). |
| **Cross-session task threading / task IDs that span sessions** | "I started a refactor in session A and finished it in session B — show me the combined spend." | Multi-session task IDs introduce a join problem, require an external task store, and break the marker-is-scoped-to-session simplicity. | Task-type is the cross-session join key — Revenium-side analytics can group by `task_type` to see all `refactor_module_x` across sessions (`PROJECT.md` Out of Scope). |
| **Classify every turn, including trivial acks** | "Just classify everything for consistency." | Pollutes the taxonomy with `acknowledgment` / `clarification_request` / etc. that have no analytical value; doubles guardrail token cost; encourages low-quality labels. | Substantive-turn-only classification, per `PROJECT.md` Key Decision. |
| **Auto-merge / auto-dedupe of taxonomy entries** | "We have `code_review` and `review_code` — collapse them automatically." | Normalization at the input layer (lowercase, snake_case) plus lookup-first discipline handles most of this. Active merging carries risk of incorrectly collapsing distinct concepts and breaking historical Revenium analytics. | Static lookup-first reuse; if drift becomes a real problem, ship a separate offline `taxonomy dedupe` script later (`PROJECT.md` Key Decision). |
| **Free-form `operation_type`** | "We have weird operation types not in Revenium's enum." | Revenium's enum *is* the wire contract. The free-form axis is `task_type` — use it. Sending unknown `operation_type` will be rejected server-side. | Map novel concepts to `task_type` (free-form); `operation_type` stays within the enum. |
| **Auto-discovery / auto-emission of new task labels without taxonomy file** | "Why do I need a taxonomy file at all? Let the agent invent labels and Revenium will sort them out." | This is the failure mode Core Value rejects: it produces `code_review` and `code-review` and `review_code` on the same host within a week. | Strict lookup-first against a written taxonomy is the load-bearing discipline (`PROJECT.md` Core Value). |
| **Modifying Hermes' `state.db` schema upstream** | "Why don't we just add a `turn_tokens` column?" | We don't own Hermes. Coupling the skill's correctness to an upstream schema change is fragile. | The marker file *is* the per-turn record, designed to work with whatever Hermes exposes (`PROJECT.md` Out of Scope). |

## Feature Dependencies

```
[Agent-managed taxonomy file]
    └──requires──> [Marker JSONL contract]
                       └──requires──> [Cron splits delta across markers]
                                          └──requires──> [Marker-aware idempotency in ledger]

[GUARDRAIL accounting]
    └──requires──> [Marker JSONL contract]
                   (the classification turn writes its own marker)

[Tag normalization]
    └──enhances──> [Agent-managed taxonomy file]
                   (case-folding on read prevents drift even if a marker slips through)

[Backward-compat default (unclassified)]
    └──conflicts──> [Strict enum on task_type]
                    (we accept unclassified as a valid value rather than rejecting it)

[Adjacent flag wins (--agent, --trace-id)]
    └──enhances──> [Marker JSONL contract]
                   (markers carry the extra context if available)
```

### Dependency Notes

- **Taxonomy requires marker contract:** The taxonomy file is only useful if there is a per-turn channel through which the agent's labels reach the cron. The marker JSONL is that channel.
- **Cron split requires marker-aware idempotency:** Once a single session-delta is split into N rows on the Revenium side, re-runs must not duplicate any one of them. This extends but does not replace the existing `HERMES:<sid>:<total_tokens>` ledger key — load-bearing per `PROJECT.md` Constraints.
- **GUARDRAIL accounting requires marker contract:** The agent writes a separate marker for the classification turn with `operation_type=GUARDRAIL`. Without markers, classification spend is indistinguishable from work spend.
- **Tag normalization enhances taxonomy:** Even with strict lookup-first, the agent might mint `Code-Review` instead of `code_review`. Normalizing on read/write of the taxonomy is cheap insurance.
- **Unclassified bucket conflicts with enum strictness:** If we ever enforced `task_type` against a hard global enum, we'd break the unclassified fallback. The decision (per Revenium API design and `PROJECT.md`) is: `task_type` stays free-form with local discipline, `operation_type` stays enum-strict.

## MVP Definition

### Launch With (v1)

The minimum viable extension that fulfills `PROJECT.md`'s Core Value: every completion shipped carries a consistent task_type, and the skill stays backward-compatible.

- [ ] Marker JSONL contract: agent appends `{ts, task_type, operation_type, ...}` per substantive turn (per `PROJECT.md` Active)
- [ ] `task-taxonomy.json` with strict lookup-first discipline in `SKILL.md` (per `PROJECT.md` Active)
- [ ] Tag normalization (lowercase + snake_case) on read/write (table stakes)
- [ ] `hermes-report.sh` reads markers, splits session delta equally across N markers, emits one `revenium meter completion` per marker (per `PROJECT.md` Active)
- [ ] Marker-aware ledger key — re-runs are idempotent at (session, marker) granularity (per `PROJECT.md` Active; load-bearing invariant)
- [ ] `--task-type unclassified` fallback when no markers exist (per `PROJECT.md` Active)
- [ ] `--operation-type GUARDRAIL` on the classifier's own turn (per `PROJECT.md` Active)
- [ ] Test coverage: marker shape, taxonomy shape, split behavior (per `PROJECT.md` Active)

### Add After Validation (v1.x)

Features to add once classification accuracy has been observed in production.

- [ ] `--agent` and `--trace-id` populated from marker context where richer values exist (per `PROJECT.md` Active — adjacent-flag-wins) — trigger: confirm Revenium-side analytics actually slice by these axes
- [ ] Taxonomy stats / linter script — count usages per label, surface near-duplicates (`code_review` vs `code-reviewed`) — trigger: drift observed in a real deployment
- [ ] Marker schema versioning — explicit `schema_version` field — trigger: first need to evolve the marker shape without breaking the cron

### Future Consideration (v2+)

Things to defer until taxonomy + equal-split prove out.

- [ ] S3 weighted split (markers carry approximate-length hints, cron weights the delta) — trigger: Revenium-side attribution drifts noticeably from observed agent behavior
- [ ] S4 guardrail-estimator split (separate cron pass that estimates classification cost specifically) — trigger: GUARDRAIL spend is large enough that equal-split distorts work-vs-overhead numbers
- [ ] Offline taxonomy dedupe / merge tool — trigger: a real host has >100 labels and demonstrable fragmentation
- [ ] Cross-skill taxonomy sharing (other Hermes skills publishing into a shared per-host taxonomy) — trigger: a second skill adopts the same metering pattern

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Marker JSONL contract | HIGH | LOW | P1 |
| `task-taxonomy.json` + lookup-first prompt discipline | HIGH | LOW (it's a `SKILL.md` change plus a JSON file) | P1 |
| Cron splits delta across markers (S2 equal split) | HIGH | MEDIUM (Python heredoc inside `hermes-report.sh`) | P1 |
| Marker-aware ledger idempotency | HIGH | MEDIUM (ledger format extension, careful migration) | P1 |
| Tag normalization on read/write | HIGH | LOW | P1 |
| `--task-type unclassified` fallback | HIGH | LOW | P1 |
| `--operation-type GUARDRAIL` for self-classification turn | HIGH | LOW | P1 |
| Test coverage for new contract | HIGH | MEDIUM | P1 |
| Adjacent-flag-wins (`--agent`, `--trace-id`) | MEDIUM | LOW | P2 |
| Marker schema versioning | MEDIUM | LOW | P2 |
| Taxonomy linter / stats | MEDIUM | LOW | P2 |
| S3 weighted split | LOW (until needed) | HIGH | P3 |
| S4 GUARDRAIL estimator | LOW (until needed) | HIGH | P3 |
| Cross-skill taxonomy sharing | LOW (out of scope today) | MEDIUM | P3 |

**Priority key:** P1 = launch blocker, P2 = next pass, P3 = defer until observed need.

## Competitor Feature Analysis

The four-axis comparison the question asks about. Each row maps a competitor capability to this project's planned approach.

| Feature | How competitors do it | Our approach | Why we diverge |
|---------|----------------------|--------------|----------------|
| **Per-call kind / type tag** | OpenInference enum (10 values), OpenLLMetry enum (4), Datadog enum (7), LangSmith semi-fixed `run_type`, OTel `gen_ai.operation.name` (well-known list) | Revenium's `operation_type` enum (17 values) — already controlled by the API, agent picks from it via the marker | We adopt the industry pattern of "fixed enum for kind." Revenium's enum is wider than OpenInference's, which gives us more headroom (e.g. `MODERATION`, `RERANK`, `VISION` separately). |
| **Free-form activity tag** | Helicone custom properties, Langfuse tags, Portkey metadata, LangSmith tags, OpenInference `tag.tags`, Braintrust tags | Revenium's `task_type` (free-form) populated from marker | Same industry pattern. We add what nobody else does: local taxonomy discipline at the *write* side. |
| **Label production mechanism** | SDK call-site decorators (LangSmith, OpenLLMetry, Phoenix, Braintrust, Datadog); HTTP headers (Helicone, Portkey); server-side log inference (other Revenium integrations) | Agent self-classification via marker JSONL, picked up by out-of-band cron | Hermes doesn't have a synchronous SDK seam we can hook (`state.db` only exposes cumulative totals; the agent can't see its own per-turn tokens). Self-classification fits the constraint and exploits the only entity that genuinely knows what just happened. |
| **Vocabulary enforcement** | Span-kind enum (universal); free-form tags/metadata with documentation-by-example only (universal); workspace-level required-fields (Portkey only) | Local `task-taxonomy.json` with strict lookup-first discipline encoded in `SKILL.md`; normalization on read/write | We solve the fragmentation problem (`code_review` vs `code-review`) that the industry leaves to users. The cost is one file on disk and a few sentences of prompt discipline. |
| **Default / unclassified bucket** | Untagged calls aggregate under "no value" in every product surveyed; Portkey explicitly recommends defaults | Always send `--task-type unclassified` explicitly | Sending the value explicitly (rather than omitting the flag) gives Revenium a clean non-null bucket. Backward-compatibility requirement per `PROJECT.md`. |
| **Classification-overhead accounting** | None surveyed | Mark the classifier's own turn with `operation_type=GUARDRAIL` so it's metered separately | Genuine differentiator. No surveyed product even has this problem because none ask the agent to classify. |
| **Attribution granularity** | Per call (SDK or gateway captures the exact tokens); per-tagged-span sums (LangSmith roll-ups) | Equal-split (S2) across N markers in a cron window | We can't do per-call because we don't see per-turn tokens. S2 is an explicit, bounded approximation, documented as such. |
| **Multi-axis grouping** | All surveyed products let you group by kind × tags × metadata in their dashboard | Revenium dashboard groups by `operation_type` × `task_type` × `agent` × `trace_id` × custom metadata | We rely on Revenium's existing analytics to do the grouping; we just stamp richer values on the wire. |

## Sources

### Primary product documentation
- [Revenium Meter AI Completion API reference](https://revenium.readme.io/reference/meter_ai_completion) — verified `task_type` is free-form, `operation_type` is the enum `CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER, TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO, VIDEO, IMAGE`
- Revenium platform docs — confirm `GUARDRAIL` bucketing for budget-enforcement overhead is in use by other Revenium integrations
- [Helicone Custom Properties docs](https://docs.helicone.ai/features/advanced-usage/custom-properties) — `Helicone-Property-<Name>` header convention, `Helicone-User-Id` as only reserved property
- [Helicone Sessions docs](https://docs.helicone.ai/features/sessions) — `Helicone-Session-Id` / `-Path` / `-Name` grouping
- [Langfuse Tags docs](https://langfuse.com/docs/observability/features/tags) — tags are 200-char strings, no vocabulary enforcement
- [Langfuse Metadata docs](https://langfuse.com/docs/observability/features/metadata)
- [Langfuse Observation Types docs](https://langfuse.com/docs/observability/features/observation-types) — fixed enum: event/span/generation/agent/tool
- [LangSmith Tags & Metadata docs](https://docs.langchain.com/langsmith/add-metadata-tags) — `run_type` plus tags/metadata
- [Portkey: Tracking Costs Per User](https://portkey.ai/docs/guides/use-cases/track-costs-using-metadata) — metadata 128-char limit, no enforced vocabulary
- [Portkey: Metadata for LLM Observability](https://portkey.ai/blog/metadata-for-llm-observability-and-debugging/)
- [OpenInference Semantic Conventions spec](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md) — `openinference.span.kind` required enum of 10 including `GUARDRAIL`; `tag.tags` free-form list
- [OpenInference spec site](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
- [OpenInference Guardrails Instrumentation](https://arize-ai.github.io/openinference/python/instrumentation/openinference-instrumentation-guardrails/)
- [OpenTelemetry GenAI Spans semconv](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) — `gen_ai.operation.name` with well-known values
- [OpenTelemetry GenAI Agent Spans semconv](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [Traceloop OpenLLMetry GenAI Semantic Conventions](https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions) — `traceloop.span.kind ∈ {workflow, task, agent, tool}`
- [Datadog LLM Observability Terms](https://docs.datadoghq.com/llm_observability/terms/) — span kinds: LLM, workflow, agent, tool, task, embedding, retrieval
- [Datadog LLM Observability Querying](https://docs.datadoghq.com/llm_observability/monitoring/querying/)
- [Braintrust Examine Traces](https://www.braintrust.dev/docs/observe/examine-traces) — span types and tags
- [Braintrust: Agent observability complete guide 2026](https://www.braintrust.dev/articles/agent-observability-complete-guide-2026) — four-span-type pattern

### Supporting / context
- [OpenLLMetry on Medium (Horovits)](https://horovits.medium.com/opentelemetry-for-genai-and-the-openllmetry-project-81b9cea6a771)
- [AgentOps taxonomy paper (arxiv 2411.05285)](https://arxiv.org/pdf/2411.05285) — academic framing of observability dimensions
- [Portkey: LLM cost attribution guide](https://portkey.ai/blog/llm-cost-attribution-for-genai-apps/)

---
*Feature research for: AI cost-metering with agent-driven task-type classification*
*Researched: 2026-05-12*
