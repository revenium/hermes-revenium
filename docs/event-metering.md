# Event-Driven Completion Metering

This is the document to have open while running the shadow, canary, and
fleet stages of the Phase 32 rollout — and the one a future reader finds
when the planning tree that designed it is gone. It covers what changed,
how to tell the two metering paths apart on a Revenium row, the switches
that control the rollout, the drain gate that protects it, the known
differences between the two paths, and what rollback can and cannot undo.

## What changed

Completion metering can now be produced by the API call that incurred it —
`post_api_request`, a hook fired once per model call — rather than
reconstructed a minute later from `state.db`'s per-session summary
counters. A new `revenium-classifier` plugin hook spools one record per
call to disk; a new cron stage (`api-event-report.sh`) enriches and ships
those records via `revenium meter completion`.

**Only completion metering moved.** Everything else about the cron
pipeline is unchanged:

- **Agentic jobs stay marker-driven, on the cron.** `post_api_request`
  carries no job lifecycle signal — nothing to move them onto. The
  `revenium-jobs.ledger` and its created-before-outcome gate are untouched.
- **Tool-event metering is untouched.** It was already event-shaped
  (`post_tool_call.sh` → `tool-event-report.sh`); this phase copied that
  pattern, not changed it.
- **Guardrail polling keeps its job.** `guardrail-check.sh` was not
  modified by any plan in this phase.

**This is not "delete the cron."** `cron.sh` grew a fifth metering stage
and a sixth gate stage; the four stages that existed before this phase all
still run, every tick, unchanged.

## The two paths, and how to tell them apart on a Revenium row

The fastest way to tell which path produced a given metered row is its
`--transaction-id`, which becomes the row's transaction identifier in
Revenium:

| Path | Transaction identifier shape | Granularity |
|------|------------------------------|-------------|
| Legacy (cron-reconstructed) | `<session_id>-<cumulative_total_tokens>-<muid>` (or `<session_id>-<cumulative_total_tokens>` for a markerless session) | One row per session-delta split, computed from `state.db` counters roughly a cron tick after the call |
| Event-driven (this phase) | `event:<api_request_id>` | One row per API call, computed from the call that incurred it |

If you are debugging a row and want to know which path shipped it, look at
the transaction identifier first — that is the question every operator
asks before anything else.

## The switches

Two independent, reversible settings control the rollout. Both are
readable from the environment (highest precedence) or from
`config.json` (checked when the environment variable is unset), with an
unrecognised value falling back to the safe default and warning exactly
once per run — a typo must never silently change what gets billed.

| Setting | Env var | `config.json` key | Default | Values |
|---|---|---|---|---|
| Event metering mode | `REVENIUM_EVENT_METERING_MODE` | `eventMeteringMode` | `shadow` | `shadow` (ships nothing, writes no ledger line, produces a comparison readout) / `live` (ships for real) |
| Legacy completions | `REVENIUM_LEGACY_COMPLETIONS` | `legacyCompletions` | `enabled` | `enabled` (the old path keeps billing) / `disabled` (request to stop — see the drain gate below) |

A fresh install of this phase's code observes **zero change**: shadow mode
ships nothing and the legacy path keeps billing exactly as it always did.
Flipping either switch is a deliberate, later operator action, not a side
effect of updating the skill.

**Shadow mode's readout.** While `REVENIUM_EVENT_METERING_MODE=shadow`
(the default), `api-event-report.sh` fully constructs every event's
`revenium meter completion` argv and then discards it — no CLI call, no
ledger line — and instead appends one JSON row per session to
`event-shadow-report.jsonl`, including sessions the event path would have
held or skipped entirely, with a per-platform aggregate (session count,
event-row count, database token total, mean coverage ratio) logged once
per run. Read this before authorising a canary: it is also how the
gateway question (does `post_api_request` fire on gateway-served turns at
all) gets answered on real traffic, before any billing changes.

## The drain gate

`drain-status.sh` answers one question: **has the legacy completions path
finished with every session it owns?** It reads exactly two local sources
— the frozen legacy ledger and `state.db` — and makes zero HTTP requests.
A session is **drained** only when both hold:

- **Terminal** — the session has ended and aged past the settle window, or
  it is gone from `state.db` entirely.
- **Quiet** — its legacy ledger timestamp has not moved across
  `REVENIUM_DRAIN_QUIET_TICKS` consecutive checks (default 15).

Exit codes: `0` drained, `10` not yet drained, `1` could not determine
(state.db or the ledger was unreadable). **Unknown never resolves to
drained** — the check is deliberately biased toward "keep waiting" over
"assume it's safe."

`hermes-report.sh` re-reads `drain-status.json`'s `drained` field at
startup, independently of anything else in this document. **A request to
set `REVENIUM_LEGACY_COMPLETIONS=disabled` is refused — with one warning
per run, and completions keep metering — while the gate reports not
drained**, or while the status file is missing or malformed. This refusal
is deliberate: the composition of "the new path skips any session already
in the legacy ledger" and "the legacy path stops when disabled" would
otherwise let a session that had prior legacy ledger lines and kept making
calls after cutover be billed by **neither** path. That is a silent
under-bill, not a crash — nothing errors, nothing halts, a slice of usage
simply never reaches Revenium. If a disable flip appears not to take
effect, run `drain-status.sh` (or `--json`) directly and look at its
`pending` list; that is the authoritative account of which sessions are
still blocking the gate and why.

## The known differences from the legacy path

- **One row per API call, not one row per session-delta split.** The
  legacy path splits a session's periodic token delta across its
  unreported markers (a GUARDRAIL/CHAT pair per classification window);
  the event path ships one row per call, carrying that call's own usage
  under a single `CHAT` operation type. Reason: the call itself, not a
  cron-tick reconstruction, is now the unit of metering.
- **No client-supplied cost.** The event path never sends `--total-cost` —
  the spooled record carries no cost field, and Revenium prices the row
  server-side from model, provider, and tokens. The legacy path's
  `--total-cost`, when present, is unaffected.
- **Provider resolution is native, except through a routing layer.** The
  event path reads the call's own `provider` field directly, unless that
  field names a routing layer (OpenRouter, a LiteLLM-substring match,
  Bedrock, `custom`, or empty/`none`/`unknown`), in which case it derives
  the model provider from `response_model` — the model that actually
  served the call, which is a strictly better input than the legacy
  path's session-level `model` column for a session that changed models
  mid-stream.

## Rollback

Setting `REVENIUM_EVENT_METERING_MODE` back to `shadow` (or leaving it at
its default) stops the event path from shipping immediately — it resumes
constructing argv and discarding it. The legacy ledger was **frozen, never
migrated** (a deliberate design choice — the two ledgers key on
per-call `api_request_id` versus per-session-total identifiers that are
not equivalent, so migrating between them risked retroactive
double-metering), so re-enabling the legacy completions stage runs against
an intact record exactly as if the event path had never shipped.

**What rollback cannot undo:** any row the event path has already shipped
to Revenium exists server-side under the `event:<api_request_id>`
transaction-identifier scheme. The legacy path cannot reproduce that key
from the frozen `HERMES:` ledger, so those specific rows cannot be
re-derived or re-shipped under the legacy shape. This is exactly why the
canary flip (letting the event path ship for real on even one profile) is
gated behind an explicit operator decision rather than happening as a
byproduct of deploying this phase's code.

## State files added

- `~/.hermes/state/revenium/api-events/<sid>.jsonl` — the per-session
  event spool, one JSON record per API call, written by the
  `post_api_request` plugin hook.
- `~/.hermes/state/revenium/revenium-api-events.ledger` — the event path's
  own idempotency ledger, keyed on `api_request_id` (`API:` lines),
  entirely separate from the legacy `revenium-hermes.ledger`.
- `~/.hermes/state/revenium/event-shadow-report.jsonl` — shadow mode's
  per-session comparison readout, bounded by the same rotation thresholds
  as the metering log.
- `~/.hermes/state/revenium/drain-status.json` — the drain gate's
  atomically-written verdict, including the pending-session list.

## Where to look if you build on this

- `skills/revenium/scripts/api-event-report.sh` — the shipper: the settle
  gate, the legacy-ledger partition, the temporal marker join, provider
  resolution, and the shadow/live mode branch.
- `skills/revenium/scripts/drain-status.sh` — the drain gate's own
  implementation and its exit-code contract.
- `skills/revenium/scripts/hermes-report.sh` — the one outer guard around
  the legacy completion-emission block that reads the drain gate.
- `tests/fixtures/compat/meter-completion-event.golden.json` — the event
  path's own pinned argv shape; see `tests/fixtures/compat/README.md` for
  how it relates to (and stays separate from) the legacy v1.x contract.
