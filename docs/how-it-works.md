# How it works

[← Documentation index](README.md)

## Token metering with task-type classification

A background cron runs every minute and executes six stages under one lock —
`plugin-status.sh`, `hermes-report.sh`, `guardrail-check.sh`,
`tool-event-report.sh`, `api-event-report.sh`, and `drain-status.sh`. The token
reporter (`hermes-report.sh`): it reads token deltas from `~/.hermes/state.db`, then ships one `revenium meter completion` per marker. Each completion carries `--task-type` and `--operation-type` drawn from the task taxonomy, and job-owning markers also receive `--agentic-job-id`. Ledger lines are `HERMES:<session_id>:<total_tokens>:<unix_ts>:<muid>`, and a session is skipped when its `(sid, total_tokens)` pair is already present, so re-running the cron never double-reports.

Task-type and agentic-job inference is performed by the deterministic `revenium-classifier` plugin (`skills/revenium/plugins/revenium-classifier/`). It reads session data directly — it does not rely on the agent voluntarily classifying its own turns. Sessions with no markers fall back to `--task-type unclassified`.

The plugin registers **four** hooks, because no single one covers every session shape: `on_session_end`, `on_session_finalize`, `post_llm_call`, and `post_api_request`. `on_session_end` fires only from the session-expiry watcher, so gateway-served sessions would never be classified by it alone; `on_session_finalize` covers shutdown, expiry, and reset boundaries, and `post_llm_call` fires once per completed turn so an ordinary prompt produces a classified job on its **first** turn rather than waiting for a session boundary. A single guard (`_session_already_classified`) makes "exactly one classification per session" hold regardless of which hook fires first. `post_api_request` carries no classification concern at all — it is the event-metering seam described below.

## Event-driven metering (the v1.5 path)

Alongside the delta-based reporter above, a second path meters **each API call
individually**. The `post_api_request` hook fires once per call and appends a
compact record to a per-session spool — no network call, no LLM, no database
read on that path — and the cron's `api-event-report.sh` stage ships each record
as its own row, keyed on the provider's own `api_request_id`. Where
`hermes-report.sh` reports a session's token *delta* and divides it across that
session's markers, the event path reports what each call actually used.

**Two switches control it, and the difference between them is the thing to get
right:**

| Variable | Default | Effect |
|---|---|---|
| `REVENIUM_EVENT_METERING_MODE` | `shadow` | `shadow` computes rows without shipping; `live` ships them. |
| `REVENIUM_LEGACY_COMPLETIONS` | `enabled` | `enabled` keeps the delta reporter billing; `disabled` stands it down. |

**Setting `MODE=live` alone does not cut over.** With legacy still enabled, which
path bills a given session is decided by an ownership record, and the outcome
depends on a race you cannot predict from the switches — see
[`docs/event-metering.md`](event-metering.md) for the mechanism and the
evidence behind it. A real cutover requires `REVENIUM_LEGACY_COMPLETIONS=disabled`.

Setting it fleet-wide is safe: profiles whose sessions have drained cut over
immediately, and the rest keep billing through the legacy path until they drain,
then cut over on their own. The `drain-status.sh` cron stage maintains that gate.
A session's effective stale threshold is
`max(REVENIUM_DRAIN_STALE_SECONDS, REVENIUM_CRON_SETTLE_SECONDS + 86400)`, and it
sets the floor on how fast a profile can converge. **Check yours before planning
a cutover — the default is not the fast case.** At the stock default
(`REVENIUM_DRAIN_STALE_SECONDS=604800`) a quiet open session takes **seven days**
to clear. Lowering it to `86400` puts the `settle + 86400` term on top, giving
`87000` seconds ≈ **24.17 hours** — the figure quoted in
[`docs/event-metering.md`](event-metering.md), which reflects one fleet's
tuned configuration rather than the default.

Rollback is the reverse and is demonstrated, not assumed:
[`docs/internal/rollback-rehearsal.md`](internal/rollback-rehearsal.md).

## Agentic job tracking

Discrete task arcs are reported as Revenium agentic jobs (`revenium jobs create` / `revenium jobs outcome`). Each arc's business outcome is recorded exactly once — outcomes are immutable and never re-sent. Idempotency is maintained in `~/.hermes/state/revenium/revenium-jobs.ledger`. AI transactions belonging to a job are linked in Revenium via `--agentic-job-id`.

Every job outcome also carries a `--metadata` JSON blob: the deployment `source` (from the session's source column) on every outcome, plus a `failure_reason` on `FAILED` arcs — a brief plain-text cause inferred by the classifier. `SUCCESS` and `CANCELLED` arcs carry source only.

## Tool-event metering

The `post_tool_call` hook captures each Hermes tool call (tool name, duration in milliseconds, success/failure, `tool_call_id`, session ID, error message) to a per-session file at `~/.hermes/state/revenium/tool-events/<sid>.jsonl`. The hook makes no network call — it is a pure local observer that exits 0 on any internal failure so it never blocks the agent. The cron's `tool-event-report.sh` stage then reads these files and ships each unledgered record via `revenium meter tool-event`, keyed on `<sid>:<tool_call_id>` in `revenium-tool-events.ledger`.

## Guardrail enforcement

Guardrail enforcement is **structural**: the `pre_llm_call` and `pre_tool_call` Hermes shell hooks check `guardrail-status.json` on every turn and act per the warn/block band, blocking the agent deterministically regardless of session length. The `SKILL.md` halt block is a procedural backstop — the hooks are the load-bearing enforcement path.

Before every operation the agent's state resolves to one of:

- **All rules ok** → proceed silently.
- **Warn-band rule active** → `pre_llm_call` emits one stderr line per (session, ruleId) and the agent continues.
- **Block-band rule active, autonomous mode** → `pre_tool_call` blocks all tool calls and emits an `action: block` response; `pre_llm_call` injects the verbatim halt directive into the turn. A notification (including the most recent enforcement-events list entry) is sent through the configured Hermes messaging channel.
- **Status file missing** → proceed with caution (fail-open).

The three shell hooks are registered by `install-hooks.sh` and removed by `uninstall-hooks.sh`. They are inert until the user approves them on first `hermes chat`. `guardrail-check.sh` (the second cron stage) refreshes `guardrail-status.json` and detects new halt transitions; on transition into halt, it embeds the latest enforcement-event into the halt notification.

The full halt/exceed contract — including the exact halt response string the agent must emit verbatim — is specified in [`skills/revenium/SKILL.md`](../skills/revenium/SKILL.md).

## `/revenium` command

Run `/revenium` at any time inside a Hermes session to:

- **View budget status** — current spend, threshold, percent used, halt state.
- **Reset** — recreate the budget rule with the same settings (zeroes current spend).
- **Reconfigure** — update API key, budget amount, or period (deletes the old budget rule and creates a new one).

