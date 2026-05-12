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

## Requirements

### Validated

<!-- Inferred from the existing skill — these are the load-bearing capabilities
this project must not break. -->

- ✓ Cron-driven metering pipeline reads `~/.hermes/state.db` and ships token
  deltas to Revenium via `revenium meter completion` — existing
  (`skills/revenium/scripts/hermes-report.sh`)
- ✓ Append-only ledger keyed on `HERMES:<session_id>:<total_tokens>` guarantees
  idempotent reporting across cron runs — existing
- ✓ Per-session delta computation: scales `input/output/cache_read/cache_write/cost`
  by `(curr - prev) / curr` against the previous ledger entry — existing
- ✓ Provider inference for `anthropic | openai | google | xai | deepseek | meta`
  including OpenRouter and Bedrock special-casing — existing
- ✓ Mandatory in-session budget check via `budget-status.json`, with verbatim
  halt-string contract in `SKILL.md` — existing
- ✓ Halt-transition detection (new vs carried-forward) and Hermes messaging-
  toolset notifications — existing (`budget-check.sh`)
- ✓ State separation: skill content under `~/.hermes/skills/revenium/`, mutable
  state under `~/.hermes/state/revenium/`, single-source paths in
  `scripts/common.sh` — existing, test-enforced
  (`tests/test_repository.py::test_runtime_paths_are_hermes_native`)

### Active

<!-- New work this project will deliver. All are hypotheses until shipped. -->

- [ ] **Agent-written turn markers.** After each *substantive* turn (skill
  prompt defines what counts), the agent appends a single JSONL line to
  `~/.hermes/state/revenium/markers/<session_id>.jsonl` capturing
  `{ts, task_type, operation_type, ...}`.
- [ ] **Agent-managed task taxonomy.** The agent owns
  `~/.hermes/state/revenium/task-taxonomy.json`, a controlled-vocabulary
  dictionary of known task labels. The skill prompt enforces a strict
  lookup-first discipline: read the taxonomy, reuse an existing label if any
  fits, only mint a new label when no existing one is appropriate.
- [ ] **GUARDRAIL accounting.** Tokens consumed by classification itself are
  metered with `--operation-type GUARDRAIL`. The agent writes a distinct
  marker for the classification turn so the cron emits a separate metering
  call for it.
- [ ] **Cron splits deltas across markers (S2 equal split).** When
  `hermes-report.sh` computes a session delta, it reads markers for that
  session written since the last ledger entry, divides the delta equally
  across N markers, and emits one `revenium meter completion` per marker with
  the marker's `--task-type` and `--operation-type`.
- [ ] **Marker-aware idempotency.** Ledger format extends so that re-running
  the cron after a partial failure does not double-report any (session,
  marker) pair. Existing `HERMES:<sid>:<total_tokens>` semantics are
  preserved where they still apply.
- [ ] **Backward-compatible default.** Sessions with no markers in the current
  window (older installs, agent didn't classify, marker file missing) emit a
  single metering call with `--task-type unclassified` and no
  `--operation-type` — never break existing behavior.
- [ ] **Adjacent flag wins.** Populate `--operation-type` for non-guardrail
  work turns from the marker (default to `CHAT` when omitted), and revisit
  the currently hardcoded `--agent "Hermes"` and `--trace-id "${sid}"` so
  they carry richer values where the agent or session metadata supports it.
- [ ] **Test coverage for the new contract.** Repository invariant tests
  cover marker-file shape, taxonomy-file shape, and the cron's split
  behavior under representative marker configurations.

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
| Controlled-vocabulary taxonomy with strict lookup-first reuse | Pure free-form labels fragment (`code_review` / `code-review` / `review_code`); a per-host taxonomy file keeps Revenium-side labels consistent | — Pending |
| Marker file (JSONL per session) is the agent ↔ cron contract | Hermes state.db has no per-turn record; the agent can't call `revenium meter completion` itself reliably without per-turn token visibility. Markers let the cron remain the source of truth for token math | — Pending |
| Equal split (S2) across markers in a cron window | Simplest defensible attribution given no per-turn token data; cleanly separates `CHAT` vs `GUARDRAIL` rows on the Revenium side; bias is bounded and roughly self-cancels at volume | — Pending |
| `--operation-type GUARDRAIL` for the classification turn | Distinguishes overhead-from-self-classification from task work in Revenium analytics; lets us measure the cost of the feature itself | — Pending |
| Default to `--task-type unclassified` on no-marker sessions | Preserves backward compat for older installs and gives Revenium a non-null bucket for unaccounted spend | — Pending |
| Classify substantive turns only, not every turn | Trivial acks and one-word replies would pollute the taxonomy and burn guardrail tokens without analytic benefit | — Pending |
| Taxonomy growth is agent-managed, no automatic merge pass | Initial scope; if drift becomes a problem in practice a periodic dedupe pass can be added later | — Pending |

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

---
*Last updated: 2026-05-12 after initialization*
