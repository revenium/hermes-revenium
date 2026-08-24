# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the git tags on
this repository.

> `hermes skills install` resolves this repository's default branch, not its tags. A tag is
> a release marker; it does not gate what installs.

## [Unreleased]

### Added
- Opt-in, off-by-default **LLM outcome evaluation** (`llmOutcomeEvaluation` in
  `config.json`): on a `SUCCESS` job arc, estimates the job's economic value via one
  bounded LLM call on the user's own provider. The result is an unverified model
  estimate — Revenium combines it with metered cost into the displayed ROI. Fails
  closed: a missing or malformed config metres exactly as before.
- The evaluation-outcome log taxonomy now distinguishes `invalid` and `timed-out` from
  `abstained`, in addition to the pre-existing `evaluated`, `deferred`, and `reported` —
  six words in total, split across two log destinations (in-process on the
  `revenium_classifier` logger for four of them, the cron's `revenium-metering.log` for
  the other two).
- `diagnose.sh` section reporting, per profile, whether LLM outcome evaluation is
  enabled, which evaluator is selected, and the two cron-side taxonomy counts.
- The pre-existing unbounded deferred/wedged job-outcome logger is now rate-limited to
  once per `(outcome_id, reason)`, with a per-tick backlog aggregate line when the
  count is non-zero.

## [v1.7] — 2026-08-22

### Added
- Skill-usage attribution on metered completions, and on the event path, for `revenium`
  CLI 1.4.0. Capability-gated, so an older CLI is unaffected. ([#81], [#82])
- `LICENSE` (MIT), backing the `license: MIT` that `SKILL.md` had declared in frontmatter
  since the first commit. ([#83])
- `CONTRIBUTING.md`, issue and pull-request templates, and a CI workflow running the test
  suite on every pull request. ([#83])
- `CHANGELOG.md`. ([#84])
- [`docs/plugin-interface.md`](docs/plugin-interface.md) — what the Hermes plugin surface
  does, measured against a live install. Shipped code depends on it: `api_event_spool.py`
  parses the payload contract it records. ([#85])

### Changed
- `README.md` split from 646 lines into a landing page plus seven guides under
  [`docs/`](docs/), and corrected to say that the working parts are a plugin, three shell
  hooks and a cron — `SKILL.md` itself is only a halt-check backstop. ([#83], [#84])
- Multi-profile guidance corrected: upgrades must re-name profiles, the restart target is
  often not the gateway, and `rsync --delete` is no longer suggested. ([#78])

### Removed
- The planning and engineering-evidence trees are no longer tracked. `.planning/` had been
  gitignored since v1.2, but 32 files were still committed; `docs/internal/` held nine
  more. ([#84])

### Fixed
- `plugin-status.sh` reported a false `firing` when a grace-window session masked a stall,
  and its remediation named the gateway on hosts where a desktop-app
  `--profile <name> serve` process owns the profile. ([#79])

## [v1.6] — 2026-08-21

Fixes the chain of silent failures that made a fresh install look successful while
classifying nothing.

### Added
- `diagnose.sh` — one read-only report covering every stage of the pipeline, ordered by how
  often each stage is the cause. ([#75], [#76])

### Fixed
- `bootstrap.sh` now ships in the skill bundle. `hermes skills install` delivers only the
  files `SKILL.md` names bundle-relative, so the documented post-install command pointed at
  a file that never arrived. ([#73])
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

A second metering path that reports what each API call actually used, rather than
apportioning a session's token delta across markers.

### Added
- Event-driven metering on the `post_api_request` hook. `api_event_spool.py` appends a
  19-key record per API call with no network, no LLM, and no sqlite in the hot path;
  `api-event-report.sh` ships each as its own row, keyed on the provider's
  `api_request_id`. Defaults to shadow mode, shipping nothing, until switched to live.
- Durable, atomically-claimed session ownership records (`owners/<sid>`), which decide
  which path bills a session, with mode-aware takeover for the event-owned/mode-revert
  hazard.
- `drain-status.sh` — a staleness-aware drain gate with a per-session legacy carve-out, so
  profiles converge on their own after `REVENIUM_LEGACY_COMPLETIONS=disabled`.
- `prune-markers.sh` for marker garbage collection, and `resolve-markers-dir.py` for
  per-session state resolution under a multiplexed gateway.

### Fixed
- Under-billing: the legacy path could claim a session it would never bill.
- Classification now reaches gateway-served sessions, via `on_session_finalize` plus a
  guarded `post_llm_call`, so an ordinary prompt produces a classified job on its first
  completed turn. `on_session_end` alone never fired for them.

## [v1.4.1] — 2026-06-25

### Added
- `--trace-type` auto-populated with the root agentic-job type, pinned per-trace and
  capability-gated for `revenium` CLI ≥ 1.2.1, so an older CLI is unaffected.
- `install.sh` — a native one-command installer.

### Fixed
- Trailing task markers now bind to the nearest preceding job.
- Setup hardening: `--reconfigure` / `--interactive` re-run gates, idempotent budget rules,
  and an `ensure_path` return-0 fix on fresh hosts.

## [v1.4] — 2026-05-29

Pushes the "one business outcome per arc" semantic through Hermes' `delegate_task()` chain,
so Revenium rolls delegated activity up under a single trace and job instead of fragmenting
it per child session.

### Added
- **Trace inheritance** — `hermes-report.sh` and `tool-event-report.sh` ship
  `--trace-id <root_sid>` for subagent sessions. Top-level sessions are unchanged from v1.3.
- **Job inheritance** — a subagent's `--agentic-job-id` is replaced with the root's job id.
  `jobs create` and `jobs outcome` are suppressed for subagents, leaving the root's ledger
  entry as the single create/outcome.
- **Marker inheritance** — `classifier.py` emits root identifiers in subagent markers.
- `scripts/get-root-session-id.py` and a `common.sh` wrapper, walking
  `state.db.sessions.parent_session_id` with a `max_depth=10` circular guard and failing
  open on a missing or locked database.
- Golden-argv compatibility fixtures pinning the wire shape of `meter completion`,
  `meter tool-event`, `jobs create`, and `jobs outcome`.

## [v1.3.1] — 2026-05-28

### Fixed
- `setup-local.sh` preflight: refuses to install when the `revenium` CLI, `sqlite3`, or
  `python3` is missing, exiting before touching anything rather than leaving a silently
  non-functional install.
- Scanner compatibility — substituted a variable for a literal config path in comments and
  prose, and collapsed verification snippets into `hooks-status.sh`. Runnable code
  unchanged; verdict `DANGEROUS → SAFE`.

### Documentation
- Rewrote the canonical install path; the prior identifiers were structurally broken for
  this skill.

## [v1.3] — 2026-05-28

Budget enforcement moved off polling `revenium alerts budget` and onto first-class
`revenium guardrails` budget rules, with two-stage warn/hard thresholds. A clean break, with
no coexistence flag, and invisible auto-migration of every existing `alertId` install on the
first cron tick. The v1.0–v1.2 metering surface flows through unchanged.

### Added
- `guardrail-check.sh` replaces `budget-check.sh` as the second cron stage, writing per-rule
  `guardrail-status.json`.
- Two-stage warn/block enforcement in `pre_llm_call.sh` and `pre_tool_call.sh`. The warn
  band emits one rate-limited stderr line per (session, ruleId) and continues; the block band
  emits the verbatim halt directive naming the offending rule.
- `setup-guardrails.sh` as the single rule-creation entry point, with three modes,
  flock-guarded, defaulting to `--filter AGENT:IS:${REVENIUM_AGENT_NAME}` and
  `--group-by AGENT`.
- An enforcement-event audit trail embedded in the halt notification, degrading gracefully
  when the API call fails.
- Shadow mode honoured end to end: shadow rules are excluded from halt derivation, and each
  breach transition gets its own one-shot `[shadow]`-prefixed notification.
- `clear-halt.sh` became ruleId-aware — `--rule-id` clears one rule, bare clears all.

### Removed
- `budget-check.sh` and `budget-status.json`.

## [v1.2] — 2026-05-19

Every Hermes tool call is metered to Revenium.

### Added
- `post_tool_call.sh` — a fail-open hook capturing a 7-key JSONL record per tool call, with
  no network call in the agent's hot path.
- `tool-event-report.sh` — a cron stage shipping events through `revenium meter tool-event`,
  idempotent on `TOOL:<sid>:<tool_call_id>`.

## [v1.1] — 2026-05-18

Discrete task arcs are tracked as Revenium agentic jobs — each created, its AI transactions
linked, and its outcome reported exactly once.

### Added
- An additive `kind:"job"` marker schema with a separate `revenium-jobs.ledger`.
- Cron-side `jobs create` with `--task-id` linkage and a fail-open CLI preflight.
- Cron-side `jobs outcome`, exactly-once, treating `HTTP 409` as success for idempotency.

## [v1.0] — 2026-05-14

Every metered completion carries a content-driven `--task-type` and `--operation-type`,
turning spend attribution from per-session totals into per-turn activity breakdowns.

### Added
- The marker contract and the cron-side split pipeline, with byte-exact conservation across
  a split and a 5-field ledger line per session.
- Wire enrichment with `--task-type` and `--operation-type`, across eight providers.
- Mechanical classification through a Hermes plugin, replacing the agent-side path.
- `prune-markers.sh`.

[Unreleased]: https://github.com/revenium/hermes-revenium/compare/v1.7...main
[v1.7]: https://github.com/revenium/hermes-revenium/compare/v1.6...v1.7
[v1.6]: https://github.com/revenium/hermes-revenium/compare/v1.5...v1.6
[v1.5]: https://github.com/revenium/hermes-revenium/compare/v1.4.1...v1.5
[v1.4.1]: https://github.com/revenium/hermes-revenium/compare/v1.4...v1.4.1
[v1.4]: https://github.com/revenium/hermes-revenium/compare/v1.3.1...v1.4
[v1.3.1]: https://github.com/revenium/hermes-revenium/compare/v1.3...v1.3.1
[v1.3]: https://github.com/revenium/hermes-revenium/compare/v1.2...v1.3
[v1.2]: https://github.com/revenium/hermes-revenium/compare/v1.1...v1.2
[v1.1]: https://github.com/revenium/hermes-revenium/compare/v1.0...v1.1
[v1.0]: https://github.com/revenium/hermes-revenium/releases/tag/v1.0
[#73]: https://github.com/revenium/hermes-revenium/pull/73
[#74]: https://github.com/revenium/hermes-revenium/pull/74
[#75]: https://github.com/revenium/hermes-revenium/pull/75
[#76]: https://github.com/revenium/hermes-revenium/pull/76
[#77]: https://github.com/revenium/hermes-revenium/pull/77
[#79]: https://github.com/revenium/hermes-revenium/pull/79
[#81]: https://github.com/revenium/hermes-revenium/pull/81
[#82]: https://github.com/revenium/hermes-revenium/pull/82
[#83]: https://github.com/revenium/hermes-revenium/pull/83
[#84]: https://github.com/revenium/hermes-revenium/pull/84
[#85]: https://github.com/revenium/hermes-revenium/pull/85
