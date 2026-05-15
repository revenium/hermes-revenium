# Hermes-Revenium Task-Type Metering

## What This Is

An extension to the existing `revenium` Hermes skill that attaches a meaningful
`--task-type` (and `--operation-type`) to every metered completion shipped to
Revenium. Today the skill reports raw token deltas with no semantic label;
after this work, every Revenium-side row carries *what the agent was doing*
when those tokens were spent, drawn from an agent-maintained controlled
vocabulary of task labels.

The audience is anyone running Hermes with the Revenium budget skill installed
who wants their AI spend analytics broken down by activity (code review,
research, refactor, planning, etc.) instead of an undifferentiated session
total.

## Core Value

**Every metered completion that leaves this skill carries an accurate,
consistently-spelled `--task-type` so Revenium analytics group spend by what
the agent actually did, not just by session.**

If the taxonomy fragments (`code_review` vs `code-review` vs `review_code`) or
attribution leaks across tasks, the feature has failed even if the wire
protocol works.

## Current Milestone: v1.1 Agentic Job Tracking

**Goal:** The skill identifies discrete task arcs as Revenium *agentic jobs* —
creating each, attributing its AI transactions, and reporting its outcome — so
spend ties to units of business work, not just sessions or turn-level
task-types.

**Target features:**

- Agent identifies task-arc boundaries and, in a FINAL ACTION marker, mints a
  business-meaningful `agenticJobId` (LLM label + entropy suffix) plus job
  name/type and a self-reported outcome (`SUCCESS` / `FAILED` / `CANCELLED`,
  with optional business `outcome-type` / `outcome-value` when it has signal).
- Cron pipeline idempotently runs `revenium jobs create`, stamps
  `--task-id <agenticJobId>` on every `meter completion` belonging to the job,
  and closes with `revenium jobs outcome` once the arc terminates.
- Job markers extend the v1.0 marker-JSONL contract; jobs sit *above*
  task-types (many task-types roll up into one job).
- Hardening: discharge v1.0 carry-forward tech debt — mint-back race
  (`fcntl.flock`), `clear-halt.sh` bash 3.2 compat, retention guard,
  dead-helper cleanup.

**Key context:** `--task-id` on `revenium meter completion` is the wire
linkage (value == `agenticJobId`). Job outcomes are immutable — one-shot — so
the idempotency invariant extends: re-running cron must never double-create a
job or double-report an outcome.

## Requirements

### Validated

<!-- v1.0 shipped 2026-05-15. Load-bearing capabilities (existing + new). -->

**Pre-existing (preserved through v1.0):**

- ✓ Cron-driven metering pipeline reads `~/.hermes/state.db` and ships token
  deltas to Revenium via `revenium meter completion` — preserved through v1.0
  with marker-aware split path layered on top
  (`skills/revenium/scripts/hermes-report.sh`)
- ✓ Append-only ledger keyed on `HERMES:<session_id>:<total_tokens>` guarantees
  idempotent reporting across cron runs — extended in v1.0 to 5-field format
  (`HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>`) with per-marker idempotency
- ✓ Per-session delta computation: scales `input/output/cache_read/cache_write/cost`
  by `(curr - prev) / curr` against the previous ledger entry — preserved with
  byte-exact field-sum conservation across N split calls (TEST-03/04)
- ✓ Provider inference for `anthropic | openai | google | xai | deepseek | meta`
  including OpenRouter and Bedrock special-casing — pinned by Phase 4
  WIRE-04 8-provider regression test
- ✓ Mandatory in-session budget check via `budget-status.json`, with verbatim
  halt-string contract in `SKILL.md` — preserved (Phase 2 halt-anchor
  byte-unchanged)
- ✓ Halt-transition detection (new vs carried-forward) and Hermes messaging-
  toolset notifications — preserved (`budget-check.sh`)
- ✓ State separation: skill content under `~/.hermes/skills/revenium/`, mutable
  state under `~/.hermes/state/revenium/`, single-source paths in
  `scripts/common.sh` — preserved, test-enforced
  (`tests/test_repository.py::test_runtime_paths_are_hermes_native`)

**Shipped in v1.0:**

- ✓ **Agent-written turn markers** — `SKILL.md` `## FINAL ACTION — TASK CLASSIFICATION` block + classifier plugin write GUARDRAIL+CHAT marker pairs to `~/.hermes/state/revenium/markers/<sid>.jsonl` (Phase 2 + Phase 6)
- ✓ **LLM-driven task classification** — `_classify_via_llm` mints specific descriptive labels from actual session content (3 quick tasks shipped 2026-05-14 closed the chain: coverage + prompt bias + content visibility)
- ✓ **Taxonomy persistence and recency-ordered prompt** — `_persist_label_to_taxonomy` (D-32) + `_read_taxonomy_labels` recency-ordered (D-33) — newly-minted labels persist back so future turns see live vocabulary (Phase 5)
- ✓ **GUARDRAIL accounting** — `--operation-type GUARDRAIL` for classification turns, `CHAT` for work turns; both flow per-marker from `markers/<sid>.jsonl` (Phase 2 + Phase 4)
- ✓ **Cron splits deltas across markers (S2 equal split)** — `hermes-report.sh::split_strategies.py` divides session delta equally across N markers per cron window; one `revenium meter completion` per marker (Phase 3)
- ✓ **Marker-aware idempotency** — per-`(sid, muid)` transaction ID + ledger row prevents double-reporting on partial-failure retry (Phase 3)
- ✓ **Backward-compatible zero-marker fallthrough** — sessions with no markers emit a single call with `--task-type unclassified --operation-type CHAT` (Phase 4 WIRE-01, D-22 gate discharged: server-side default is `CHAT`; idempotent for existing dashboards/budgets)
- ✓ **Adjacent flag passthrough** — `--operation-type` / `--agent` / `--trace-id` populated per-marker with colon-dash fallbacks to today's hardcoded values; cron is pure pass-through (D-23 — no upstream writer changes required) (Phase 4 WIRE-02/03)
- ✓ **Mechanical classification** — `revenium-classifier` `hermes_cli` plugin on `on_session_end` writes markers for every `run_conversation()` exit — universal session coverage including gateway-internal cron tickers; subagent inheritance via `state.db.sessions.parent_session_id` (Phase 6 — surfaced by Phase 3 UAT)
- ✓ **Marker file pruning** — operator-invoked `prune-markers.sh` (ledger-based staleness, 30-day default + `$REVENIUM_MARKER_RETENTION_DAYS` env override, dry-run, info-helper logging) keeps marker dirs bounded on long-running hosts (Phase 5)
- ✓ **Test coverage** — 45 invariant tests covering marker shape, taxonomy shape, cron split behavior, 8-provider regression, pipe-safety sanitization, prune E2E, classifier dedupe / inheritance / budget-halt / fail-open

### Active

<!-- v1.1 scope. REQ-IDs assigned in REQUIREMENTS.md; this is the feature-level view. -->

**Agentic job tracking:**

- [ ] Agent mints a per-task-arc `agenticJobId` (LLM business label + entropy suffix) with job name/type in a FINAL ACTION marker.
- [ ] Agent self-reports a job outcome (`SUCCESS` / `FAILED` / `CANCELLED`) plus optional business `outcome-type` / `outcome-value`.
- [ ] Job markers extend the v1.0 marker-JSONL contract; many task-types roll up under one `agenticJobId`.
- [ ] Cron idempotently runs `revenium jobs create` per `agenticJobId`.
- [ ] Cron stamps `--task-id <agenticJobId>` on every `meter completion` belonging to a job.
- [ ] Cron closes terminated arcs with `revenium jobs outcome` exactly once.
- [ ] Backward compatibility: marker-less and job-less sessions meter exactly as v1.0 does today.

**Hardening (v1.0 carry-forward):**

- [ ] **Mint-back race window fix.** Add `fcntl.flock` to `_persist_label_to_taxonomy` (currently uses fixed `.tmp` filename without lock; two concurrent `on_session_end` events can race).
- [ ] **`clear-halt.sh` bash 3.2 compat.** Same `${VAR@Q}` pattern that broke `prune-markers.sh` on Mac Studio is latent-broken in `clear-halt.sh:17`.
- [ ] **Retention guard.** Validate `REVENIUM_MARKER_RETENTION_DAYS >= 1` in `prune-markers.sh` (currently 0 silently deletes everything).
- [ ] **Dead helper cleanup.** Remove `_count_tools_in_current_turn` if no callers exist post-v1.0 (kept per D-37 deferred).

### Out of Scope

- **Modifying Hermes' `state.db` schema or proposing per-turn token columns
  upstream** — we don't own Hermes; this project lives inside the boundaries
  of what the skill can observe.
- **Real-time / mid-turn metering** — we accept per-cron-cycle attribution
  (worst case: ~60s lag). Synchronous metering from inside the agent's turn
  is rejected on complexity grounds.
- **Per-turn token exactness** — S2 equal split is the accepted approximation
  of token-per-marker attribution. Agent-weighted (S3) and guardrail-
  estimator (S4) splits are deferred; we'll revisit only if Revenium
  attribution drifts noticeably in practice.
- **Retroactive classification of historical sessions** — only sessions whose
  turns the agent classified going forward get task-types. No backfill.
- **Cross-session task IDs / multi-session task threading** — markers and
  task-type are scoped to a single Hermes session.
- **Server-side taxonomy curation on Revenium** — taxonomy lives locally on
  the host; how Revenium chooses to surface or normalize labels is its
  concern, not this skill's.

## Context

**Repo shape.** `hermes-revenium` is a distribution package, not an
application. The skill lives at `skills/revenium/` so `hermes skills tap add`
discovers it under the default `skills/` path. There is no build step, no
compiled artifact, and no runtime here — installs copy the skill into
`~/.hermes/skills/revenium/`. `tests/test_repository.py` enforces frontmatter,
state-path discipline, and a clean-fork branding guard.

**Two-half coupling.** The skill has two halves that communicate exclusively
through flat files under `~/.hermes/state/revenium/`:

1. The cron pipeline (`cron.sh` → `hermes-report.sh` + `budget-check.sh`),
   which runs every minute outside any Hermes session.
2. The in-session skill prompt (`SKILL.md`), which is loaded on every Hermes
   turn and instructs the agent to read `budget-status.json` before any costly
   operation and to emit the verbatim halt string when halted.

The two halves never call each other directly. The shape of `config.json` and
`budget-status.json` is their public interface; this project adds a third file
on the contract — the per-session marker JSONL — and a fourth — the
agent-owned taxonomy.

**Why now.** `revenium meter completion` exposes `--task-type`,
`--operation-type`, `--agent`, and `--trace-id` flags today; the skill uses
almost none of them. The cumulative-tokens-per-session view that's currently
shipped tells you how much you're spending but not what you're spending on.
Closing that gap unlocks meaningful per-activity analytics on the Revenium
side.

**Constraint that shapes the design.** `state.db` only exposes per-session
cumulative totals — there are no per-turn token records to mine. The agent
can't see its own per-turn token counts either. This is why marker files are
necessary and why attribution is approximate, not exact.

## Constraints

- **Tech stack**: Bash + Python heredocs + sqlite3 + the `revenium` CLI, with
  `set -uo pipefail` (or `-euo pipefail` for simpler scripts). No new runtime
  dependencies — anything new must be expressible in stdlib Python or POSIX
  sh.
- **State path discipline**: All new files live under
  `~/.hermes/state/revenium/`. Paths are declared in `scripts/common.sh` and
  nowhere else; `test_runtime_paths_are_hermes_native` will fail the build if
  this is violated.
- **No writes to `state.db`**: The skill is a pure consumer of Hermes'
  session DB. This is enforced socially today and must remain true.
- **Tap discoverability**: The skill must stay at `skills/revenium/`. Frontmatter
  in `skills/revenium/SKILL.md` requires `name: revenium`, the `metadata.hermes`
  block, and `category: devops` — enforced by
  `test_skill_frontmatter_has_hermes_metadata`.
- **Legacy branding guard**: `test_no_legacy_branding_left` greps every text
  file against a regex of forked-from product names; new docs and code must
  not reintroduce them.
- **Idempotency**: Re-running the cron must never double-report. This is the
  load-bearing invariant of the existing ledger and must extend to the new
  marker-split flow.
- **Backward compatibility**: Existing installs with no markers must continue
  to meter exactly as they do today, just with `--task-type unclassified`.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Granularity = per turn, not per session | Per-session loses the signal the user actually wants; one Hermes session can span many distinct activities | — Pending |
| Agent self-classifies after each substantive turn | LLM-classify-after-the-fact and skill-name-derived approaches were rejected: the former duplicates the agent's own knowledge; the latter is too coarse | — Pending |
| LLM mints specific labels; reuses only on exact match | Pure free-form labels fragment (`code_review` / `code-review` / `review_code`); a per-host taxonomy file keeps Revenium-side labels consistent. Lookup-first reuse pressure removed via quick task 260514-nfb — LLM now mints specific descriptive labels by default and reuses only when the same specific work recurs | Shipped (Phase 5) |
| Marker file (JSONL per session) is the agent ↔ cron contract | Hermes state.db has no per-turn record; the agent can't call `revenium meter completion` itself reliably without per-turn token visibility. Markers let the cron remain the source of truth for token math | — Pending |
| Equal split (S2) across markers in a cron window | Simplest defensible attribution given no per-turn token data; cleanly separates `CHAT` vs `GUARDRAIL` rows on the Revenium side; bias is bounded and roughly self-cancels at volume | — Pending |
| `--operation-type GUARDRAIL` for the classification turn | Distinguishes overhead-from-self-classification from task work in Revenium analytics; lets us measure the cost of the feature itself | — Pending |
| Default to `--task-type unclassified` on no-marker sessions | Preserves backward compat for older installs and gives Revenium a non-null bucket for unaccounted spend | — Pending |
| D-07 heuristic skip removed (was dead code) | The D-07 heuristic skip predicate (`tool_count == 0 AND len(response) < 200`) was always true because `response=None` is always passed from the plugin entrypoint, silently dropping ~94% of sessions. Removed via quick task 260514-n8e; the classifier now fires on every session end | Shipped (Phase 5) |
| Taxonomy growth is agent-managed, no automatic merge pass | Initial scope; if drift becomes a problem in practice a periodic dedupe pass can be added later | — Pending |
| v1.1: job granularity = per task arc, not per session | Per-session jobs lose the business-outcome signal; an arc (a goal-directed sequence of turns) is the natural unit. Reuses the v1.0 LLM-classification machinery | — Pending |
| v1.1: agent declares the job once, at arc end, in the FINAL ACTION marker | Mirrors the v1.0 classify-at-end pattern; cron does create+meter+outcome in one cycle. Avoids start/end marker-pair discipline | — Pending |
| v1.1: `agenticJobId` = LLM business label + entropy suffix | Human-readable in the Revenium UI; entropy suffix prevents the taxonomy-style fragmentation/collision seen in v1.0 | — Pending |
| v1.1: `--task-id` on `meter completion` is the tx→job wire link | CLI exposes `--task-id` (value == `agenticJobId`) for correlation; no HTTP shim or SDK dependency needed | — Pending |
| v1.1: job outcomes are immutable — cron reports each exactly once | Revenium `jobs outcome` is one-shot; the v1.0 ledger idempotency invariant extends to job-create and outcome-report | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

## Evolution Notes

Dated record of decisions that were rewritten after shipping. Each entry cites the originating quick task or phase that triggered the change.

| Date | Decision | Quick Task | Change Summary |
|------|----------|------------|----------------|
| 2026-05-14 | D-3 (taxonomy reuse) | 260514-nfb | Lookup-first reuse pressure removed. LLM now mints specific descriptive labels by default and reuses only when the same specific work recurs. Live evidence: 12 of 16 markers landed on `generation` with old framing; mint-first prompt eliminated the collapse. |
| 2026-05-14 | D-8 (trivial-skip) | 260514-n8e | D-07 heuristic skip was dead code — `response=None` always collapses the `len(response) < 200` predicate to `True`, silently dropping ~94% of sessions. Removed from `classifier.py`; classifier now fires on every `on_session_end` event. |

---
*Last updated: 2026-05-15 — Phase 7 complete (job-marker schema & state scaffolding: `kind:"job"` contract frozen, `revenium-jobs.ledger` declared, cron reader branches on `kind`)*
