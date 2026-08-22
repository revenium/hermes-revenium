# How it works

[← Documentation index](README.md)

This ships as a Hermes skill bundle, but the skill itself — `SKILL.md` — only carries a
halt-check backstop. The work is done by a plugin, three shell hooks, and a cron. See
[What's actually installed](../README.md#whats-actually-installed) for the split.

Those pieces fall into three parts, and they never call each other. The only coupling is
files under `~/.hermes/state/revenium/`.

1. **In-session.** The `revenium-classifier` **plugin** — Python that Hermes loads from
   `~/.hermes/plugins/` and calls at four lifecycle hooks — labels what each session was
   doing and writes marker files. Three **shell hooks**, registered in `config.yaml`,
   enforce guardrails and capture tool calls. None of this makes a network call.
2. **State files.** `config.json`, `guardrail-status.json`, the markers, the ledgers, the
   taxonomies. Every process re-reads what it needs; there is no shared memory and no IPC.
3. **The cron pipeline.** Once a minute, out of process, under one lock. This is the only
   part that talks to Revenium.

That separation is deliberate. A broken install degrades to "no enforcement, no
classification" — never to "agent blocked".

## Token metering with task-type classification

The cron runs six stages under one lock: `plugin-status.sh`, `hermes-report.sh`,
`guardrail-check.sh`, `tool-event-report.sh`, `api-event-report.sh`, and `drain-status.sh`.

`hermes-report.sh` is the token reporter. It reads token deltas from `~/.hermes/state.db`
and ships one `revenium meter completion` per marker. Each completion carries
`--task-type` and `--operation-type` from the task taxonomy; markers that own a job also
carry `--agentic-job-id`.

It reports deltas, not totals. Ledger lines look like
`HERMES:<session_id>:<total_tokens>:<unix_ts>:<muid>`, and a session whose
`(sid, total_tokens)` pair is already present is skipped, so re-running the cron never
double-reports.

The labels come from the `revenium-classifier` plugin, which reads session data directly
rather than asking the agent to classify its own turns. A session with no markers falls
back to `--task-type unclassified`.

The plugin registers four hooks, because no single one covers every session shape:

| Hook | Why it exists |
|---|---|
| `on_session_end` | Fires only from the session-expiry watcher, so it alone would never see a gateway-served session. |
| `on_session_finalize` | Covers shutdown, expiry, and reset boundaries. |
| `post_llm_call` | Fires once per completed turn, so an ordinary prompt is classified on its first turn instead of waiting for a session boundary. |
| `post_api_request` | Carries no classification concern — it is the event-metering seam described below. |

One guard, `_session_already_classified`, makes "exactly one classification per session"
hold no matter which hook fires first.

## Event-driven metering (the v1.5 path)

A second path meters each API call individually. `post_api_request` fires once per call and
appends a compact record to a per-session spool — no network call, no LLM, no database read
on that path — and the cron's `api-event-report.sh` stage ships each record as its own row,
keyed on the provider's `api_request_id`.

The difference from the reporter above is what gets attributed. `hermes-report.sh` takes a
session's token delta and divides it across that session's markers. The event path reports
what each call actually used.

Two switches control it:

| Variable | Default | Effect |
|---|---|---|
| `REVENIUM_EVENT_METERING_MODE` | `shadow` | `shadow` computes rows without shipping; `live` ships them. |
| `REVENIUM_LEGACY_COMPLETIONS` | `enabled` | `enabled` keeps the delta reporter billing; `disabled` stands it down. |

**Setting `MODE=live` alone does not cut over.** While legacy stays enabled, an ownership
record decides which path bills a given session, and the outcome turns on a race you cannot
predict from the switches. A real cutover needs `REVENIUM_LEGACY_COMPLETIONS=disabled`.
[Event metering](event-metering.md) has the mechanism and the evidence.

Setting that fleet-wide is safe. Profiles whose sessions have drained cut over at once; the
rest keep billing through the legacy path until they drain, then cut over on their own. The
`drain-status.sh` stage maintains that gate.

A session's effective stale threshold is
`max(REVENIUM_DRAIN_STALE_SECONDS, REVENIUM_CRON_SETTLE_SECONDS + 86400)`, and it sets the
floor on how fast a profile can converge. **Check yours before planning a cutover — the
default is not the fast case.** At the stock `REVENIUM_DRAIN_STALE_SECONDS=604800`, a quiet
open session takes seven days to clear. Lower it to `86400` and the `settle + 86400` term
takes over, giving 87,000 seconds, or about 24.17 hours. That is the figure quoted in
[Event metering](event-metering.md), and it reflects one fleet's tuned configuration rather
than the default.

Rollback is the reverse, and it is demonstrated rather than assumed:
[rollback rehearsal](internal/rollback-rehearsal.md).

## Agentic job tracking

Discrete task arcs become Revenium agentic jobs through `revenium jobs create` and
`revenium jobs outcome`. Each arc's business outcome is recorded exactly once — outcomes
are immutable and never re-sent — with idempotency held in
`~/.hermes/state/revenium/revenium-jobs.ledger`. The AI transactions belonging to a job are
linked back through `--agentic-job-id`.

Every outcome also carries a `--metadata` blob holding the deployment `source`, taken from
the session's source column. `FAILED` arcs add a `failure_reason`: a short plain-text cause
inferred by the classifier. `SUCCESS` and `CANCELLED` arcs carry source alone.

## Tool-event metering

`post_tool_call` captures each Hermes tool call — name, duration in milliseconds,
success or failure, `tool_call_id`, session ID, error message — into
`~/.hermes/state/revenium/tool-events/<sid>.jsonl`.

The hook is a pure local observer. It makes no network call and exits 0 on any internal
failure, so it can never block the agent. The cron's `tool-event-report.sh` stage reads
those files and ships each unledgered record through `revenium meter tool-event`, keyed on
`<sid>:<tool_call_id>` in `revenium-tool-events.ledger`.

## Guardrail enforcement

Enforcement is structural. The `pre_llm_call` and `pre_tool_call` hooks read
`guardrail-status.json` on every turn and act on the warn/block band, which blocks the
agent deterministically no matter how long the session has run. The halt block in
`SKILL.md` is a procedural backstop; the hooks are the load-bearing path.

Before every operation the state resolves to one of four cases:

| State | What happens |
|---|---|
| All rules ok | Proceed silently. |
| A rule in the warn band | `pre_llm_call` emits one stderr line per (session, ruleId); the agent continues. |
| A rule in the block band, autonomous mode | `pre_tool_call` blocks every tool call with an `action: block` response, `pre_llm_call` injects the halt directive verbatim, and a notification carrying the latest enforcement event goes out through the configured Hermes messaging channel. |
| Status file missing | Proceed. Every in-session path fails open. |

`install-hooks.sh` registers the three hooks and `uninstall-hooks.sh` removes them. They
stay inert until approved on first `hermes chat`.

`guardrail-check.sh` refreshes `guardrail-status.json` each tick and detects new halt
transitions. Only a new transition notifies, and only `clear-halt.sh` can clear a halt —
nothing auto-clears.

The full halt contract, including the exact string the agent must emit verbatim, is in
[`SKILL.md`](../skills/revenium/SKILL.md).

## The `/revenium` command

Run `/revenium` inside a Hermes session to:

- **View budget status** — current spend, threshold, percent used, halt state.
- **Reset** — recreate the budget rule with the same settings, zeroing current spend.
- **Reconfigure** — change API key, budget amount, or period. This deletes the old rule and
  creates a new one.
