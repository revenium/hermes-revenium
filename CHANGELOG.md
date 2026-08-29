# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the git tags on
this repository.

> `hermes skills install` resolves this repository's default branch, not its tags. A tag is
> a release marker; it does not gate what installs.

## [Unreleased]

Two rounds of work on the same experimental feature. The first shipped LLM outcome
evaluation; the second replaced most of its internals so a model estimate can no longer
read as an observed result. The feature stays **opt-in and off by default** throughout,
and an install that leaves it off meters byte-identically to before.

### Documentation

- **[Job value and ROI](docs/value-and-roi.md)** — a dedicated reference for the whole
  experimental value path, replacing the fragments previously spread across the README,
  `docs/how-it-works.md`, `docs/configuration.md`, `references/config-schema.md`, and
  `references/job-declaration.md`. It documents, in one place, what was previously in no
  document at all: the evaluator call's own bounds, the eight-word abstention vocabulary,
  the full sidecar field inventory, the exact `--metadata` key order on the wire, the two
  truncation tiers, the correction record shape, the ledger lines, retention and pruning,
  and a symptom-to-cause troubleshooting table. The pages it was extracted from keep their
  summaries and link to it.

### Added — evidence grading and economic mechanisms

- **Nine evidence labels** (`evidence_class`), replacing the single forced constant.
  They are deliberately **not** a confidence ladder: customer confirmation can be
  commercially authoritative yet causally weak, observation proves that something
  happened rather than what produced it, and configuration establishes an approved rate
  rather than hours actually spent. The naked-LLM path always resolves to
  `MODEL_ESTIMATED_DEMO` and **cannot** promote itself to any observed,
  customer-confirmed, associational, or impact label — enforced structurally, and proven
  by adversarial fixtures rather than asserted. Exact spellings and the resolution rule
  are in [`references/job-declaration.md`](skills/revenium/references/job-declaration.md).
- **Six economic mechanisms** (`economic_mechanism`) in place of the previous
  hours-times-rate assumption: labor substitution, augmentation or capacity expansion,
  quality or decision improvement, risk avoidance, newly enabled work, and incremental
  revenue. The evaluator may select three of them; the other three are operator-declared
  (see Known limitations).
- **Net value across supplied costs** (`net_value`). A new `costs` config block, keyed by
  job type, subtracts `human_review`, `rework_or_error`, `handoff`, and
  `training_or_change` from the estimated value. A supplied `0` and an absent category are
  different things and both are explicit in the record. There is no fleet-wide default —
  an unconfigured job type nets nothing.
- **Explicit zero and unknown denominators.** AI cost is never silently substituted when
  the claim concerns total workflow investment; no ratio is emitted.
- **Double-counting controls** (`double_counting_group`) so one outcome cannot be fully
  credited to several jobs, or claimed twice across overlapping mechanisms.
- **Zero and negative work stays visible.** Failed, cancelled, abandoned, and unclassified
  jobs receive no positive value by default while retaining their metered and allocated
  cost, so negative net value remains legible instead of disappearing.
- **Bounded low/base/high estimates** in preference to false precision. Reversed or
  unordered bounds abstain rather than guess.

### Added — persistence, corrections, and provenance

- **A sidecar assessment record** under `${STATE_DIR}/job-assessments/`, keyed by job id.
  The richer assessment no longer competes for the 1024-byte marker line, which a
  six-field assessment had already filled to about 70%.
- **Append-only corrections.** `correct-assessment.sh` writes a `kind:"correction"` line
  locally and calls `revenium jobs outcome-update` server-side. The original assessment is
  preserved; nothing is destructively replaced. Operator-only, never run from cron.
- **Provenance that survives deferral and retry.** Model, prompt, taxonomy, policy, and
  schema versions persist through a failed job creation and its retry, so a later
  taxonomy or prompt change never silently rewrites history.
- **The deciding model is recorded** separately from `evaluator`/`evaluator_version`,
  which identify the implementation rather than the model that produced the estimate.
- **`studyId` / `studyVersion`** config keys let an install name an impact study its
  assessments reference. Referencing a study never changes an assessment's own
  `evidence_class`.

### Added — boundaries, reporting, and privacy

- **Six pluggable boundaries as real contracts** — classification, output/outcome
  assessment, economic valuation, evidence resolution and reportability, cohort impact
  (contract only), and Revenium reporting — selected through a `boundaries` config object.
  A non-LLM implementation can be added behind any of them without masquerading as an LLM
  evaluator. The contracts are host-agnostic, so the core can later be extracted.
- **`ImpactStudyResult` as a contract only** — fields for study identity, estimand,
  identification method, effect interval, assumptions, and validity scope. No estimators
  and no experiment orchestration ship here.
- **`experimentalReportEstimates`**, a second literal-boolean gate independent of
  `enabled`. Left off, an estimate is computed and recorded locally but its value is
  withheld from Revenium — the outcome and provenance still report
  (`reportability_status: "candidate"`). Turned on, the value ships as well
  (`reportability_status: "reportable"`). The resolver decides this, never the evaluator.
- **A bounded `--metadata` envelope** with a byte ceiling, tier-ordered shedding, and a
  `metadata_truncated` marker when a tier actually drops keys. An over-ceiling payload
  never ships unmarked, and base metering never breaks on a field the API does not know.
- **Inference-locality provenance.** A derived address class and provider are recorded;
  the raw `base_url` is consumed and discarded, never persisted or transmitted. The docs
  state plainly that this records where inference was **configured** to go, not where data
  stayed.
- **No raw prompt or transcript text** reaches any marker, ledger, queue, log, or
  `--metadata` field, proven by a dynamically enumerated canary sweep whose
  vacuous-pass guard is itself proven binding by a negative control.

### Added — documentation and guards

- **[Claim distinctions and evidence boundaries](docs/claim-distinctions-and-evidence-boundaries.md)** —
  output vs. outcome vs. valuation vs. impact vs. ROI, the results chain, the
  product-truth boundary, correction and audit behaviour, abstention and negative value,
  and what this work deliberately does not ship.
- **A prohibited-claim-language guard** (`test_no_prohibited_claim_language_left`) in the
  shape of the existing legacy-name guards, scanning the whole shipped tree rather than
  Markdown alone, so an overreaching claim cannot ship in a code comment or a log string.
- **Two source-derived documentation guards** pinning the documented envelope key
  inventory and byte ceiling to the reporter's live constants, so the docs cannot drift
  from the code.

### Known limitations

- `quality_decision_improvement`, `risk_avoidance`, and `incremental_revenue` are
  representable and forward correctly on the wire, but nothing can currently select them:
  no config key, no CLI flag, and `correct-assessment.sh` does not set a mechanism. A
  study reference is the intended producer.
- When a configured `boundaries.valuation` or `boundaries.evidence` implementation
  declares its own `evidence_class`, the persisted record still shows the evaluator's
  class. The effect is conservative — `MODEL_ESTIMATED_DEMO` is the weakest label, so the
  record under-claims — and no promotion path is opened. Resolving it needs a
  cross-boundary precedence rule.
- `revenium jobs roi` surfaces no provenance, so the evidence label and assumptions are
  retained in the bounded metadata envelope and locally, not shown in that view. Use
  `revenium jobs outcome-history` to read them back.
- This round has not been exercised against a live tenant. The end-to-end proof is a
  fixture harness driving the real classifier and reporter with a stubbed model response.

### Added — LLM outcome evaluation (initial)
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
