# Project Research Summary

**Project:** Hermes-Revenium Task-Type Metering
**Domain:** Agent-driven task classification on top of an existing file-coupled, two-half (in-session prompt + out-of-process cron) metering skill
**Researched:** 2026-05-12
**Confidence:** MEDIUM-HIGH (HIGH on architecture/format mechanics; MEDIUM on agent-classification ergonomics — direction is novel)

## Executive Summary

This is a brownfield extension to the `revenium` Hermes skill that adds per-turn task attribution to the existing token-delta metering pipeline. The four research dimensions reinforce — rather than contradict — the existing PROJECT.md: the agent self-classifies each substantive turn into a controlled vocabulary, writes a per-session JSONL marker, and the once-per-minute cron splits the session token delta across the markers it finds. The contract surface grows by exactly two files (`task-taxonomy.json`, `markers/<sid>.jsonl`) and one extended ledger row format; everything else (Bash + stdlib Python + sqlite3 + `revenium` CLI, paths declared in `scripts/common.sh`) stays the same.

The strongest external finding is that **no surveyed competitor ships agent self-classification as a first-class feature** — Helicone, Langfuse, LangSmith, Portkey, Phoenix, Braintrust, Datadog, and the OTel GenAI spec all rely on SDK call-site decorators, HTTP gateway headers, or post-hoc log inference. The Hermes constraint (`state.db` exposes only per-session cumulative totals; the agent cannot see its own per-turn tokens) forces this design and turns what looks like a workaround into a genuinely novel attribution mechanism. The matching novelty on the wire is using `GUARDRAIL` (from the OpenInference span_kind vocabulary) for the classification turn itself, so the cost of the feature is measurable in Revenium.

The dominant risk is not the wire protocol — it's the prompt. `SKILL.md` already has a load-bearing halt-check framed as "ABSOLUTE FIRST — NON-NEGOTIABLE"; adding several paragraphs of taxonomy-lookup and marker-write instructions can dilute that priority anchor and silently weaken budget enforcement. Mitigation is structural: ship the prompt design phase before the marker-file phase, end-load the new instructions, push details into `references/`, and add prompt-invariant tests that assert the halt block still appears in the expected position. The other top risks (taxonomy fragmentation, equal-split bias direction, ledger idempotency under partial failure) all have concrete, MVP-shippable mitigations identified in the research.

## Key Findings

### Recommended Stack

No new runtime dependencies. The additions are all expressible in stdlib Python and POSIX sh, consistent with the no-new-deps constraint. The two non-obvious choices are the use of **OpenInference span_kind values** (not OpenTelemetry GenAI) for `--operation-type`, and **per-session JSONL with POSIX `O_APPEND`** for the agent→cron marker contract.

**Core technologies (additions only):**
- **JSON Lines (jsonlines.org)** — per-session marker file format; append-friendly, line-oriented, parseable by a Python heredoc, no schema framework needed.
- **OpenInference span_kind vocabulary (STABLE 1.x)** — authoritative values for `--operation-type`. Includes `GUARDRAIL` explicitly, which the OTel GenAI `gen_ai.operation.name` enum does NOT define. OTel GenAI is still "Development" status and is verb-shaped rather than category-shaped; OpenInference is a better fit for analytics on the Revenium side. A future flip to OTel would be a flat string-substitution.
- **POSIX `O_APPEND` + single-write semantics** — atomicity guarantee for marker writes; one writer per session means no flock is strictly required for markers, but `fcntl.flock` is cheap belt-and-suspenders for taxonomy mutations (write-to-tmp + `os.rename`).
- **Python `json`, `fcntl`, `os.fsync`** — stdlib only; already available everywhere the skill runs.

**Suggested seed taxonomy** drawn from the OpenLLMetry RFC #3460 (`gen_ai.task.type` draft: `research`, `analysis`, `generation`, `review`) plus Hermes-flavored extensions (`refactor`, `planning`, `debugging`). There is **no industry-standard controlled vocabulary** for AI agent task types as of 2026 — this is uncharted territory.

See: `.planning/research/STACK.md`

### Expected Features

The Revenium API contract is fixed: `task_type` is **free-form text** (with examples), `operation_type` is a **17-value enum** (`CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER, TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO, VIDEO, IMAGE`). Every feature below has to fit through that contract.

**Must have (table stakes — 2026 industry baseline):**
- Per-completion `task_type` on the wire (every surveyed product supports some form of this).
- `operation_type` drawn from a controlled enum (every surveyed product enforces a span-kind enum of some kind).
- Backward compatibility — sessions without classification still meter, attributing to an explicit `--task-type unclassified` bucket.
- Idempotent attribution across cron retries — load-bearing invariant of the existing ledger, extended to per-(session, marker) granularity.
- Tag normalization — case, separators, whitespace — without it the "consistently-spelled" Core Value promise is broken.
- Distinction between "what kind of call" (op_type) and "what activity" (task_type) — every observability product splits these into two axes.

**Should have (genuine differentiators — verified absence in competitors):**
- **Agent-managed local taxonomy file with strict lookup-first reuse** — no surveyed product solves the free-form-tag fragmentation problem (`code_review` vs `code-review` vs `review_code`).
- **Agent self-classification (post-turn)** — structurally distinct from SDK-decorator and gateway-header patterns; well-matched to the Hermes constraint that there are no per-turn token records to mine.
- **GUARDRAIL accounting for self-classification overhead** — no surveyed product separates "tokens spent classifying" from "tokens spent doing the work" because no product asks the agent to classify.
- **Equal-split (S2) attribution documented as an explicit, bounded approximation** — honest framing rather than hidden imprecision.

**Defer (v2+):**
- S3 weighted split (markers carry length hints) — trigger: Revenium-side attribution drifts noticeably in practice.
- S4 GUARDRAIL estimator (separate pass) — trigger: GUARDRAIL share is large enough that equal-split distorts work-vs-overhead numbers.
- Offline taxonomy dedupe / merge tool — trigger: >100 labels with demonstrable fragmentation.
- Cross-session task threading, real-time metering, server-side taxonomy curation — explicitly out of scope per PROJECT.md.

See: `.planning/research/FEATURES.md`

### Architecture Approach

The skill's existing two-half decoupling (skill prompt ↔ cron, communicating only via flat files under `~/.hermes/state/revenium/`) is preserved. The contract surface grows by exactly two new files and one extended ledger row format. The two halves still never call each other directly.

**Major components:**
1. **Skill prompt (`SKILL.md`)** — extended with a post-budget-check classification block: lookup-first taxonomy read, conservative mint, marker append, GUARDRAIL marker for the classify turn itself. End-loaded so it doesn't displace the halt-check.
2. **`common.sh`** — adds `TAXONOMY_FILE` and `MARKERS_DIR` to the single source of truth for paths; ensures `mkdir -p` on install. Path-discipline test extended to cover the new vars.
3. **`hermes-report.sh` (extended cron)** — for each session with a positive delta, reads markers since the previous ledger row's `ts`, splits the delta equally across N markers (last absorbs remainder), emits one `revenium meter completion` per marker with per-marker `--task-type` / `--operation-type` / per-marker `--transaction-id`. Falls through to the existing single-call path when N == 0.
4. **Marker file (`markers/<sid>.jsonl`)** — per-session append-only JSONL. The agent is the only writer; cron is read-only. Records < 1 KB, written with a single `write()`, guaranteed atomic on local POSIX filesystems.
5. **Taxonomy file (`task-taxonomy.json`)** — single JSON file the agent reads on every classification turn and mutates with a write-to-tmp + `os.rename` under `fcntl.flock`. Allow-listed schema.
6. **Extended ledger row** — `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>`. Legacy 4-field rows remain parseable; new code always writes the 5-field form. This is the load-bearing invariant of marker-aware idempotency: re-running the cron after a partial failure must not double-report or lose any (session, marker) pair.

The agent-writes-/-cron-reads split for markers mirrors the existing `budget-status.json` (cron-writes-/-agent-reads) shape — same contract pattern, opposite direction.

See: `.planning/research/ARCHITECTURE.md`

### Critical Pitfalls

1. **Prompt-priority fragility for `SKILL.md`** — `SKILL.md` is reloaded every turn but competes with user prompts, tool outputs, and error tracebacks. The existing halt-check survives because it's framed as "ABSOLUTE FIRST — NON-NEGOTIABLE" in one sentence. Adding several paragraphs of taxonomy/marker instructions risks displacing that anchor. **Mitigation:** end-load the new content, push details to `references/`, ship the prompt design phase BEFORE the marker-file phase, add prompt-invariant tests asserting the halt block still appears in the expected position. Halt-check regression is the single most dangerous outcome of this project.
2. **Taxonomy fragmentation under nominally-strict lookup-first prompts** — LLMs drift to near-duplicates (`code_review` / `code-review` / `CodeReview`) under long context and varying naming-convention pressure. **Mitigation:** pre-write normalization (lowercase + snake_case + regex) enforced cron-side (don't trust the agent alone); fuzzy-match in the lookup prompt; soft ceiling at ~25 labels; periodic `dedupe-taxonomy.py` pass. Fragmenting taxonomies are very hard to merge retroactively.
3. **Ledger idempotency breaks under partial multi-call failure** — when one delta becomes N meter calls and call 3 of 5 fails, the existing `HERMES:<sid>:<total_tokens>:<ts>` ledger row records no per-marker provenance. Next tick sees no new delta, skips the session, and call 3 is lost forever. **Mitigation:** version-bump the ledger to `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>`; write the ledger line per-call (not per-batch); extend the Revenium `--transaction-id` to `${sid}-${total_tokens}-${muid}` so server-side dedupe catches retries even if the local ledger is lost. This must ship as one coherent migration.
4. **Equal-split (S2) bias is one-directional, not self-cancelling** — PROJECT.md Key Decisions claims the bias "roughly self-cancels at volume," but the research shows the bias **systematically favors smaller turns**. Classification turns are almost always shorter than work turns, so GUARDRAIL share is structurally overstated. An 8000-token work turn paired with a 300-token classify turn gets 50/50, not 96/4. **Mitigation:** document the bias direction in `references/setup.md` ("GUARDRAIL share is an upper bound"); ship a synthetic-bias test that pins the known behavior rather than hiding it; emit a cron-side warning when a window is classification-dominated; make the split strategy pluggable so S3/S4 can drop in later. **Worth surfacing as a contradiction with PROJECT.md.**
5. **Agent forgets to write the marker** — context dilution at long sessions (instruction adherence degrades past ~3,000 tokens of context) plus the "boring terminal step" nature of marker writes means the agent will silently skip. Result: `unclassified` dominates Revenium-side analytics. **Mitigation:** move the marker write into a SKILL.md FINAL ACTION section with a canonical example; make the cost of forgetting visible via cron-side telemetry; don't try to enforce inline (don't add competing "ABSOLUTE" framings). Accept the dropout rate and rely on the documented fallback.
6. **Backward-compatibility regression — totals change for existing users** — sum of N split calls must equal what the legacy single call would have reported. Integer-division remainder lost, or implicit `--operation-type` server-side default changing cost calculations, both regress trust. **Mitigation:** conservation test (`sum(split) == input delta` for every numeric column); no-marker path emits argv differing from legacy only by `--task-type unclassified`; verify Revenium server-side `operation_type` default semantics (via the Revenium `manage_metering` tool) BEFORE shipping any explicit default.

Additional pitfalls covered in detail: substantive-turn judgment drift in both directions, marker-file growth in long sessions starving the cron, concurrent reader/writer races, privacy leakage via free-form `description` fields, and `unclassified` dominance from over-strict substantive judgment.

See: `.planning/research/PITFALLS.md`

## Implications for Roadmap

The architecture research's "Build Order" section gives a clean dependency-driven phase decomposition. The PITFALLS research adds one critical re-ordering: **prompt design must ship before marker-file mechanics**, because the halt-check regression risk is the only HIGH-cost recovery scenario in the whole project.

### Phase 1: Path Foundation (no behavior change)

**Rationale:** Every later phase reads `TAXONOMY_FILE` and `MARKERS_DIR` from `common.sh`. Landing them in isolation keeps the change small, lets `test_runtime_paths_are_hermes_native` move forward independently, and unblocks downstream phases without coupling them.

**Delivers:** `common.sh` additions for `TAXONOMY_FILE` and `MARKERS_DIR`; `mkdir -p` for the new directory; chmod 700 on the markers directory (security defense in depth); updated path-discipline test.

**Addresses:** Foundation for every Active item in PROJECT.md.

**Avoids:** Pitfall 10 (marker directory permissions, baked in from day one).

### Phase 2: Prompt Design (SKILL.md classification block)

**Rationale:** The PITFALLS research identifies prompt-priority fragility as the single most dangerous risk. Ship the prompt changes before the marker-writer infrastructure so we can verify the halt-check still fires reliably in long-session scenarios before cron behavior changes. End-load new instructions; push details to `references/task-taxonomy.md`; keep canonical examples over rule lists per Anthropic context-engineering guidance.

**Delivers:** Extended `SKILL.md` with end-loaded classification block (lookup-first taxonomy discipline, substantive-turn definition with canonical examples, FINAL ACTION marker write, GUARDRAIL marker for the classify turn itself); new `references/task-taxonomy.md`; seed `task-taxonomy.json` with the OpenLLMetry RFC starting labels plus Hermes-flavored extensions; allow-listed marker schema documented; static blocklist for trivial labels (`ack`, `greeting`, etc.).

**Uses:** OpenInference span_kind vocabulary for the `operation_type` field documentation.

**Implements:** The agent half of the agent ↔ cron contract.

**Avoids:** Pitfalls 1 (taxonomy fragmentation — normalization baked into the prompt), 2 (substantive-turn judgment — hard rule + canonical examples), 6 (agent forgets — FINAL ACTION pattern), 7 (prompt-priority fragility — end-loading + references/), 10 (privacy — allow-listed schema documented before agents start writing).

### Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 Migration

**Rationale:** This is the load-bearing infrastructure change. It must land as one coherent migration because partial adoption (split path without per-marker ledger lines, or new ledger without conservation test) breaks the idempotency invariant. Lands as the cron understanding markers, splitting deltas, AND versioning the ledger together — never piecemeal.

**Delivers:** Extended `hermes-report.sh` with: marker reader (tail-from-`prev_ts`, skip-muids-already-in-prev-row), equal-split arithmetic with remainder-on-last, per-call `revenium meter completion` invocation with extended `--transaction-id`, per-call ledger append (not per-batch), 5-field ledger row writes with legacy 4-field row read fallback, fallthrough single-call path for N == 0 with explicit `--task-type unclassified`. Cron lockfile via `flock(2)` to prevent overlapping ticks. Pluggable split strategy hook.

**Uses:** Python heredocs for marker reading and split arithmetic; `fcntl` for the cron lockfile.

**Implements:** The cron half of the agent ↔ cron contract; load-bearing idempotency invariant; backward-compat fallthrough.

**Avoids:** Pitfalls 3 (marker file growth — tail-reading from `prev_ts`, lockfile), 4 (concurrent writer/reader race — reader tolerates torn last line), 5 (S2 bias direction — pluggable strategy + warning log + synthetic-bias test), 8 (ledger idempotency under partial failure — v2 row + per-call writes + extended transaction-id), 9 (backward-compat regression — conservation test + byte-identical legacy argv).

**Research flag:** **Verify Revenium server-side `--operation-type` default before shipping.** Use the Revenium `manage_metering` tool to confirm what happens when `--operation-type` is absent today; if shipping `--operation-type CHAT` explicitly changes a cost calculation, the migration needs a separate signposted release note.

### Phase 4: Adjacent-Flag Enrichment + Operator Tooling

**Rationale:** Once markers are flowing in real traffic, enrich the wire with richer `--agent` and `--trace-id` values sourced from marker fields (currently hardcoded). Add operator-facing tooling (`tools/audit-taxonomy.py`, `scripts/show-recent-markers.sh`) so operators can spot pitfalls 1, 2, and 6 before they become Revenium-side problems.

**Delivers:** `--agent` and `--trace-id` populated from marker context where richer values exist; `tools/audit-taxonomy.py` (group labels by normalized + stemmed form, propose merges); `scripts/show-recent-markers.sh <session_id>` debug helper; cron-side telemetry log lines for sessions with tokens but no markers and for classification-dominated windows.

**Implements:** PROJECT.md "adjacent flag wins" Active item.

**Avoids:** Pitfalls 1, 2, 5, 6 (operator visibility for all of them).

### Phase 5: Housekeeping (Marker Pruning + Closed-Session Rotation)

**Rationale:** Marker files will accumulate as sessions die. The rename-to-`.closed` convention costs nothing if designed in from Phase 3 but removing the actual files needs explicit operator-invocable tooling. Pure operational hygiene; no functional dependency on any prior phase.

**Delivers:** `scripts/prune-markers.sh` that removes marker files for sessions whose latest-reported ledger row is > N days old; documented manual invocation; optional daily-cron hookup.

**Avoids:** Pitfall 3 (long-tail of the marker-file growth problem).

### Phase Ordering Rationale

- **Phase 1 first** because path declarations are the foundation every other phase depends on.
- **Phase 2 BEFORE Phase 3** is the critical re-ordering driven by PITFALLS research. We need to verify in real Hermes sessions that the halt-check still fires reliably AFTER the new prompt content is added — and we need to do that verification before cron behavior changes, so any halt-check regression is unambiguously attributable to the prompt change.
- **Phase 3 as one coherent migration** because the marker reader, the equal-split, and the v2 ledger format are mutually dependent for idempotency. Shipping any subset breaks the load-bearing invariant.
- **Phase 4 after Phase 3** because adjacent-flag enrichment requires markers actually flowing, and operator tooling is most useful once there are real labels to audit.
- **Phase 5 last** because it's pure operational hygiene with no functional dependency.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** Revenium server-side `--operation-type` default behavior must be verified via the `manage_metering` tool before the cron starts defaulting to `CHAT`. Otherwise we risk Pitfall 9 (silent cost-calculation changes for existing users).
- **Phase 3:** S2 split bias direction warrants one more pass during planning — the synthetic-bias test design needs to pin the known direction, not hide it. Confirm with the team that the documented bias framing is acceptable before shipping.
- **Phase 2:** Long-session halt-check survivability after prompt additions needs a manual end-to-end test plan against representative session lengths (Hermes context-window behavior may vary by model and conversation length).

Phases with standard patterns (skip research-phase):
- **Phase 1:** Standard `common.sh` path additions; pattern is well-established in the repo.
- **Phase 5:** Standard housekeeping script; mirrors `clear-halt.sh` in shape.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | OpenInference spec confirmed STABLE 1.x; POSIX `O_APPEND` semantics verified against multiple sources; JSONL format trivially stable; OTel GenAI "Development" status verified. The OpenLLMetry RFC seed taxonomy is MEDIUM (draft RFC, not registry). |
| Features | MEDIUM-HIGH | Competitor product behavior verified directly against vendor docs (HIGH); "differentiator" claims rest on verified absence across surveyed products (MEDIUM — absence is hard to prove definitively but the surveyed docs are consistent); Revenium API contract verified against API reference (HIGH). |
| Architecture | HIGH | File-contract / idempotency / atomicity design verified against existing code and POSIX semantics; backward-compat fallthrough mirrors the existing fail-open ledger pattern. Taxonomy ergonomics is MEDIUM (best-judgment given agent read/write patterns; no prior art for agent-self-classification at this granularity). |
| Pitfalls | MEDIUM-HIGH | Direct domain experience is thin in the literature (the design is somewhat novel), but each component pitfall (controlled-vocabulary drift, JSONL growth, O_APPEND races, idempotency under partial failure, long-context prompt degradation) maps onto well-established prior art. |

**Overall confidence:** MEDIUM-HIGH. The mechanics of the proposed system are well-understood; the open question is whether agent self-classification produces useful labels in practice — answerable only by shipping a pilot and observing.

### Gaps to Address

- **Revenium server-side `--operation-type` default behavior** — verify via the `manage_metering` tool before Phase 3 ships. Affects Pitfall 9 (backward-compat regression).
- **PROJECT.md "bias self-cancels" framing contradicts PITFALLS research** — the equal-split bias is one-directional and systematically overstates GUARDRAIL share, not self-cancelling. Worth a quick re-confirmation with the team and a PROJECT.md Key Decisions update at the next phase transition; ship the bias warning in `references/setup.md` regardless.
- **Halt-check survivability under context pressure after prompt additions** — needs manual end-to-end verification before Phase 3 changes any cron behavior. No automated test can simulate full Hermes context dynamics.
- **Substantive-turn definition needs canonical-example pairing in real conditions** — the rule + examples in Phase 2 will need iteration once we see marker patterns from a real pilot. Plan for a Phase 2.5 prompt tune.
- **No prior art for agent-managed taxonomy at this scale** — we're inventing the operator UX. Plan to ship the `audit-taxonomy.py` tooling in Phase 4 and revisit the soft 25-label ceiling based on what we see.

## Sources

### Primary (HIGH confidence)
- OpenInference Semantic Conventions (Arize-AI) — STABLE 1.x span_kind enum; defines `GUARDRAIL`
- Revenium Meter AI Completion API reference (revenium.readme.io) — verified contract: free-form `task_type`, 17-value `operation_type` enum
- JSON Lines spec (jsonlines.org) — format properties
- POSIX write(3p) spec — `O_APPEND` atomicity guarantee
- Appending to a File from Multiple Processes (Chris Wellons, nullprogram.com/blog/2016/08/03/)
- Effective context engineering for AI agents (Anthropic) — canonical-example guidance informs prompt design
- Existing code: `skills/revenium/scripts/hermes-report.sh`, `scripts/common.sh`, `SKILL.md` — current behavior pinned

### Secondary (MEDIUM confidence)
- Helicone / Langfuse / LangSmith / Portkey / Phoenix / Braintrust / Datadog / OTel GenAI vendor docs — verified competitor behavior; "no competitor ships agent self-classification" is verified-absence, which is structurally MEDIUM
- OpenTelemetry GenAI Spans semconv — status "Development"; mentioned only as future-migration reference
- Context Degradation in LLMs (Emergent Mind) — instruction-adherence degradation around 3,000 tokens informs Pitfalls 6 and 7
- Stripe / AWS / Adyen idempotency guides — per-call commit boundary patterns inform Pitfall 8 mitigation

### Tertiary (LOW confidence)
- OpenLLMetry RFC #3460 — draft RFC proposing `gen_ai.task.type`; seed taxonomy is useful but not authoritative
- macOS-specific `O_APPEND` atomicity floor (observed as low as 256 bytes in some benchmarks) — drives the < 1 KB record-size discipline but the exact floor is folklore-grade
