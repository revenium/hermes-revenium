# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the git tags on
this repository.

> **Two version namespaces share these numbers, and they do not mean the same thing.**
> The tags below are *product releases*. The milestone documents under
> [`docs/internal/`](docs/internal/) are *planning cycles* — release v1.5, for instance,
> delivered planning milestone v1.4 (phases 33–35). Read `milestone-v1.4-closeout.md` as
> the closeout of a planning cycle, never as the release notes for tag v1.4.

> `hermes skills install` resolves this repository's default branch, not its tags. A tag
> is a release marker; it does not gate what installs.

## [Unreleased]

### Added
- `LICENSE` (MIT). `skills/revenium/SKILL.md` had declared `license: MIT` in frontmatter
  since the first commit with no file backing it. A test now ties the declaration and the
  file together in both directions. ([#83])
- `CONTRIBUTING.md`, issue and pull-request templates, and a CI workflow running the test
  suite on every pull request. ([#83])
- Skill-usage attribution on metered completions, and on the event path. ([#81], [#82])

### Changed
- `README.md` split from 646 lines into a 129-line landing page plus seven guides under
  [`docs/`](docs/); engineering evidence moved to `docs/internal/`. ([#83])
- Multi-profile signposting corrected throughout: upgrades must re-name profiles, the
  restart target is often not the gateway, and `rsync --delete` is no longer suggested.
  ([#78])

### Documentation
- Planning-milestone v1.4 closeout, with a convergence re-sample. ([#80])

### Fixed
- `plugin-status.sh` reported a false `firing` when a grace-window session masked a stall,
  and its remediation named the gateway on hosts where a desktop-app
  `--profile <name> serve` process owns the profile. ([#79])
- `test_shell_wrapper_fails_open_without_interpreter` hid `python3` by putting bash's own
  directory on `PATH` — `/bin` on macOS, but `/usr/bin` on Linux, where `python3` sits
  beside it. Pre-existing; it surfaced only once CI ran the suite on Linux. ([#83])

## [v1.6] — 2026-08-21

**Install and diagnosis.** Fixes the chain of silent failures that made a fresh install
look successful while classifying nothing.

### Added
- `diagnose.sh` — one read-only report covering every stage of the pipeline, ordered by
  how often each stage is the cause. ([#75], [#76])

### Fixed
- `bootstrap.sh` now ships in the skill bundle. `hermes skills install` delivers only the
  files `SKILL.md` names bundle-relative, so the documented post-install command pointed
  at a file that never arrived. ([#73])
- `install.sh` confirms the whole `revenium` CLI config on every interactive run, api-url
  included, with current values as defaults. A stale api-url used to survive unseen and
  surface later as an opaque `HTTP 403`. ([#74])
- `plugin-status.sh` no longer reports a false all-clear on hosts whose sessions never
  end — it had been structurally blind to the outage it exists to catch. ([#76])
- `guardrail-status.json` is scoped to this install's rules, and duplicate rule names no
  longer collapse two rules onto one ruleId. ([#76])
- `bootstrap.sh --update` refreshes an existing install instead of latching onto whatever
  `scripts/` arrived the first time. ([#77])

## [v1.5] — 2026-08-20

**Event-driven metering, fleet cutover, and the evidence for it.** A second metering path
that reports what each API call actually used, rather than apportioning a session's token
delta across markers — plus the 2026-08-19 cutover of all ten fleet profiles onto it.

### Added
- Event-driven metering on `post_api_request`: `api_event_spool.py` appends a 19-key
  record per API call with no network, no LLM, and no sqlite in the hot path;
  `api-event-report.sh` ships each as its own row keyed on the provider's
  `api_request_id`. Landed shadow-default, shipping nothing, then hardened over six
  evidence-driven fixes.
- Durable, atomically-claimed session ownership records (`owners/<sid>`) — the arbiter
  deciding which path bills a session — with mode-aware takeover for the
  event-owned/mode-revert hazard.
- `drain-status.sh`: a staleness-aware drain gate with a per-session legacy carve-out, so
  profiles converge on their own after `legacy=disabled`.
- `prune-markers.sh`, `resolve-markers-dir.py`, and substantial classifier rewrites.

### Fixed
- Under-billing found by a live canary: legacy must not claim a session it will never bill.
- Classification reaches gateway sessions at last, via `on_session_finalize` plus a guarded
  `post_llm_call`, so an ordinary prompt produces a classified job on its first completed
  turn.

### Evidence
Four git-tracked documents record what did and did not hold:

- `cutover-convergence-and-read-side-proof.md` — 8 of 10 profiles converged unforced. The
  *without manual intervention* clause is recorded UNATTESTED, not proven. Every non-cost
  dimension confirmed on Revenium's read side.
- `transition-reconciliation.md` — the known canary is the only session ever billed by both
  paths, fleet-wide across three independent signals. Arithmetic closes to 2 tokens for the
  five profiles a reconciliation exists for.
- `rollback-rehearsal.md` — rollback demonstrated live rather than asserted. Its restoration
  criterion is recorded NOT MET: a benign but unpermitted 1,939-record `owners/` backfill.
- `event-metering.md` — corrected twice. `mode=live` alone does not cut over, and the
  mechanism is an ownership record rather than cron stage order.

Three claims this release falsified with its own evidence, recorded rather than smoothed:
that `mode=live` alone cuts over; that legacy wins by stage order (it loses the race on a
backlogged profile); and that multi-model attribution structurally cannot be recorded.

**Known open:** nothing warns an operator about backlog size before a cutover, which is a
billing-race trigger, and whether other profiles share that race is unsurveyed. Cost
remains $0 by operator decision.

**Tag history:** the tag moved twice on 2026-08-21, both times for documentation only. The
code is unchanged from the original `3b804b0`. `3b804b0 → 8f2979e` was a README currency
fix ([#70]); `8f2979e → 142e3b5` added the hero banner ([#71]).

### Testing
Suite grown to 553 tests across 41 new test files.

## [v1.4.1] — 2026-06-25

**Trace-type metering, native one-command install, and scanner clearance.**

### Added
- `--trace-type` auto-populated with the root agentic-job type, pinned per-trace and
  capability-gated for `revenium` CLI ≥ 1.2.1 (backward compatible).
- `install.sh` — a native one-command installer.

### Fixed
- Trailing task markers now bind to the nearest preceding job.
- Setup hardening: `--reconfigure` / `--interactive` re-run gates, idempotent budget rules,
  and an `ensure_path` return-0 fix on fresh hosts.
- Scanner verdict moved `DANGEROUS → CAUTION`.

### Documentation
Remote-host upgrade guide, plus install and setup corrections.

## [v1.4] — 2026-05-29

**Subagent trace and agentic-job inheritance.** Pushes the "one business outcome per arc"
semantic through Hermes' `delegate_task()` chain, so Revenium rolls delegated activity up
under a single trace and job instead of fragmenting it per child session.

### Added
- **Trace inheritance** — `hermes-report.sh` (per-marker and fallthrough) and
  `tool-event-report.sh` ship `--trace-id <root_sid>` for subagent sessions. Top-level
  sessions stay byte-identical to v1.3.
- **Job inheritance** — a subagent's `--agentic-job-id` is replaced with the root's job id,
  race-aware; the rare race-window omission is documented as best-effort. `jobs create` and
  `jobs outcome` are suppressed for subagents, leaving the root's ledger entry as the single
  create/outcome.
- **Marker inheritance** — `classifier.py` emits root identifiers in subagent
  `GUARDRAIL`+`CHAT` markers.
- `scripts/get-root-session-id.py` plus a `common.sh` wrapper, walking
  `state.db.sessions.parent_session_id` with a `max_depth=10` circular guard, failing open
  on a missing or locked database.
- Four golden-argv compatibility fixtures and a v1.x umbrella trip-wire.

### Testing
121 → 130 tests, green on Python 3.12 and on Mac Studio (bash 3.2.57 / Python 3.9.6). Live
`delegate_task()` round-trip verified end to end.

## [v1.3.1] — 2026-05-28

Bundles four independent fixes.

### Fixed
- **Scanner compatibility** — substituted `${HOOKS_CONFIG_FILE}` for a literal config path
  in shell comments and prose, and collapsed verification snippets into `hooks-status.sh`.
  Runnable code unchanged; verdict `DANGEROUS → SAFE` on Hermes v0.15.0.
- **`setup-local.sh` preflight** — refuses to install when the `revenium` CLI, `sqlite3`,
  or `python3` is missing, exiting before touching anything rather than leaving a silently
  non-functional install.

### Documentation
- Rewrote the canonical install path, the prior identifiers being structurally broken for
  this skill.
- Reframed the tap-shadowing failure as a different skill registered under the same name,
  rather than as a stale registry entry.

## [v1.3] — 2026-05-28

**Guardrails-native budget enforcement.** Enforcement moved off polling
`revenium alerts budget` and onto first-class `revenium guardrails` budget rules with
two-stage warn/hard thresholds and an enforcement-event audit trail. A clean break, with
no coexistence flag, and invisible auto-migration of every existing `alertId` install on
the first cron tick. The v1.0–v1.2 metering surface flows through byte-identically.

### Added
- `guardrail-check.sh` replaces `budget-check.sh` as the second cron stage, writing
  per-rule `guardrail-status.json`.
- Two-stage warn/block enforcement in `pre_llm_call.sh` and `pre_tool_call.sh`: the warn
  band emits one rate-limited stderr line per (session, ruleId) and continues; the block
  band emits the verbatim halt directive naming the offending rule.
- `setup-guardrails.sh` as the single rule-creation entry point, with three modes,
  flock-guarded, defaulting to `--filter AGENT:IS:${REVENIUM_AGENT_NAME}` and
  `--group-by AGENT`.
- An enforcement-event audit trail embedded in the halt notification, degrading gracefully
  on API failure.
- Shadow mode honoured end to end: shadow rules are excluded from halt derivation, and each
  breach transition gets its own one-shot `[shadow]`-prefixed notification.
- `clear-halt.sh` became ruleId-aware — `--rule-id` clears one, bare clears all.

### Removed
- `budget-check.sh` and `budget-status.json`, deleted outright.

## [v1.2] — 2026-05-19

**Agent tool-usage tracking.** Every Hermes tool call is metered to Revenium.

### Added
- `post_tool_call.sh`, a fail-open hook capturing a 7-key JSONL record per tool call with
  no network in the agent's hot path.
- `tool-event-report.sh`, a cron stage shipping events through `revenium meter tool-event`,
  idempotent on `TOOL:<sid>:<tool_call_id>`.

### Testing
81 → 89 tests, verified live on bash 3.2.57.

## [v1.1] — 2026-05-18

**Agentic job tracking.** Discrete task arcs are tracked as Revenium agentic jobs — each
created, its AI transactions linked, and its outcome reported exactly once.

### Added
- An additive `kind:"job"` marker schema with a separate `revenium-jobs.ledger`.
- An agent-side job-declaration prompt block.
- Cron-side `jobs create` with `--task-id` linkage and a fail-open CLI preflight.
- Cron-side `jobs outcome`, exactly-once, treating HTTP 409 as success for idempotency.

## [v1.0] — 2026-05-14

**Task-type metering.** Every metered completion now carries a content-driven
`--task-type` and `--operation-type`, turning spend attribution from per-session totals
into per-turn activity breakdowns.

### Added
- State-path discipline as the foundation.
- The marker contract, initially agent-side via a `SKILL.md` final action.
- The cron-side split pipeline, with byte-exact conservation and a 5-field ledger.
- Wire enrichment plus an 8-provider regression.
- Mechanical classification through an `on_session_end` plugin, replacing the agent-side
  path.
- `prune-markers.sh` and operational hygiene.

[Unreleased]: https://github.com/revenium/hermes-revenium/compare/v1.6...main
[v1.6]: https://github.com/revenium/hermes-revenium/compare/v1.5...v1.6
[v1.5]: https://github.com/revenium/hermes-revenium/compare/v1.4.1...v1.5
[v1.4.1]: https://github.com/revenium/hermes-revenium/compare/v1.4...v1.4.1
[v1.4]: https://github.com/revenium/hermes-revenium/compare/v1.3.1...v1.4
[v1.3.1]: https://github.com/revenium/hermes-revenium/compare/v1.3...v1.3.1
[v1.3]: https://github.com/revenium/hermes-revenium/compare/v1.2...v1.3
[v1.2]: https://github.com/revenium/hermes-revenium/compare/v1.1...v1.2
[v1.1]: https://github.com/revenium/hermes-revenium/compare/v1.0...v1.1
[v1.0]: https://github.com/revenium/hermes-revenium/releases/tag/v1.0
[#70]: https://github.com/revenium/hermes-revenium/pull/70
[#71]: https://github.com/revenium/hermes-revenium/pull/71
[#73]: https://github.com/revenium/hermes-revenium/pull/73
[#74]: https://github.com/revenium/hermes-revenium/pull/74
[#75]: https://github.com/revenium/hermes-revenium/pull/75
[#76]: https://github.com/revenium/hermes-revenium/pull/76
[#77]: https://github.com/revenium/hermes-revenium/pull/77
[#78]: https://github.com/revenium/hermes-revenium/pull/78
[#79]: https://github.com/revenium/hermes-revenium/pull/79
[#80]: https://github.com/revenium/hermes-revenium/pull/80
[#81]: https://github.com/revenium/hermes-revenium/pull/81
[#82]: https://github.com/revenium/hermes-revenium/pull/82
[#83]: https://github.com/revenium/hermes-revenium/pull/83
