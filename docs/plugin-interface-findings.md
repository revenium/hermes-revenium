# Hermes Plugin Interface — Live Findings Against v0.20.1

Measured findings from driving the Hermes plugin surface live against a
**v0.20.1 (2026.8.13)** install, recorded so they survive deletion of the working
tree. Dated 2026-08-13; one correction applied 2026-08-15 (see "Corrections").

## Why this document exists

These results came from a spike whose own notes live in a directory excluded from
version control. Four of them are load-bearing for future work on this skill, and
one is a **negative** result that prevents a change which looks like a
simplification and would silently break halt enforcement. A finding that only
exists in an untracked directory is a finding that did not happen — this file is
the committed mirror.

The measurements were taken against a local OpenAI-compatible mock, so no model
spend was involved and no production data appears here.

## Verdict summary

| ID | Finding | Status |
|---|---|---|
| E1 | Registered prompt sections **cannot** carry live halt state — they freeze at session start | **Load-bearing negative.** Do not move live state into a prompt section. |
| E2 | `post_api_request` is a complete real-time metering event, with a natural idempotency key | Basis for the event-driven metering phase |
| E3 | `ctx.state` and an out-of-process cron can safely share state under `fcntl` | Viable, with a named coupling risk |
| E4 | `exit 2` and `fail_closed` both work in the hook dispatcher | `fail_closed` is a policy decision, not a free win |

---

## E1 — Prompt sections cannot carry live halt state

`ctx.register_system_prompt_section(id, content, *, position="after_memory", max_chars=4000)`
accepts a callable receiving a session-info mapping (`cwd`, `model`, `platform`,
`profile_name`, `provider`, `session_id`).

**Experiment.** One session, one process. The section callable read
`guardrail-status.json` at render time. A `post_llm_call` hook flipped `halted` to
`true` mid-session. The mock returned a tool call on the first main-loop turn,
forcing a second main-loop LLM call within the same session.

| Event | Observed |
|---|---|
| `section_render` | fired **exactly once** (`call_no=1`) |
| halt flipped to `true` | after render, before turn 2 |
| Main-loop call 1 system prompt | `halted=False` |
| Main-loop call 2 system prompt (same session) | `halted=False` ← **stale** |

**The section is frozen at session start. A halt arriving mid-session never
reaches it.**

**Why this matters.** It is tempting to "simplify" the `SKILL.md` halt-check
backstop — and its manual context-dilution runbook in
`skills/revenium/references/halt-survivability.md` — into a registered prompt
section, because sections survive compression rebuilds and fresh-process resume
byte-identically. Doing so would silently break enforcement for the exact case
that matters: a halt firing during a long autonomous run.

**Correct division of labor:**

- **Prompt section** → the *standing* instruction. Durable and compression-proof;
  legitimately retires the dilution-survivability concern for the instruction half.
- **`pre_llm_call` hook** → *live* halt state. Remains load-bearing. Do not remove.

Also observed: auxiliary calls (title generation) do **not** receive plugin prompt
sections. Only the main loop does.

## E2 — `post_api_request` is a complete real-time metering event

**Hook lifecycle, verified live per surface:**

| Surface | Result |
|---|---|
| CLI query (`-z`) | `on_session_start`, `pre`/`post_llm_call`, `pre`/`post_tool_call`, `pre`/`post_api_request`, **`on_session_end`** all fire |
| Cron (`hermes cron run`) | **identical full lifecycle**, including `on_session_end`; session id shaped `cron_<job>_<ts>` |
| Gateway | **not driven live** — no messaging credentials on the probe machine. See the caveat below. |

`pre`/`post_llm_call` fire **once per turn**; `pre`/`post_api_request` fire **once
per API call** (2 calls in the tool-call session). **That distinction is the
metering seam.**

**Captured `post_api_request` payload** (real, from the probe; identifiers
replaced with their shapes):

```json
{
  "usage": {"input_tokens":100,"output_tokens":5,"cache_read_tokens":0,
            "cache_write_tokens":0,"reasoning_tokens":0,"request_count":1,
            "prompt_tokens":100,"total_tokens":105},
  "model": "mock-model", "response_model": "mock-model",
  "provider": "custom", "base_url": "http://127.0.0.1:8099/v1",
  "session_id": "<session>",
  "task_id":    "<uuid>",
  "turn_id":    "<session>:<task>:<turn>",
  "api_request_id": "<session>:<task>:<turn>:api:<n>",
  "api_mode": "chat_completions", "api_call_count": 1,
  "telemetry_schema_version": "hermes.observer.v1",
  "platform": "cli"
}
```

This supplies, per API call and in real time, everything `hermes-report.sh`
currently reconstructs by polling `state.db` and computing scaled deltas:

- **`api_request_id` is a natural idempotency key** (`<session>:<task>:<turn>:api:<n>`).
  Each event is already a delta — no ledger delta-scaling math, and no
  `HERMES:<sid>:<total_tokens>` key.
- **`provider` + `base_url` arrive as data**, so the provider-inference Python
  heredocs in `hermes-report.sh` become unnecessary.
- **`response_model` is the model that actually served** and is fallback-aware,
  fixing the multi-model misattribution baked into reading a single
  `sessions.model` column per session.
- **`platform`** identifies the surface (`cli` / `cron` / gateway) for free.
- Cache and reasoning tokens break out natively.
- `telemetry_schema_version` gives a versioned contract to pin against.

**A first-party reference implementation exists.** The bundled
`plugins/observability/langfuse` is a first-party analog of this repo. It registers:

```
pre_api_request → post_api_request (usage) → api_request_error
pre_llm_call / post_llm_call / pre_tool_call / post_tool_call
on_session_finalize → handler
on_session_end     → SAME handler          # both events, one handler
subagent_start / subagent_stop
```

Two things follow:

1. **Registering both `on_session_end` and `on_session_finalize` against one
   handler is exactly what first-party does.** That is this skill's Phase 29
   pattern — keep it, do not "simplify" it away.
2. **Port langfuse's sanitized-response fix rather than rediscovering it.** It
   carries a load-bearing comment: on gateway turns `response` is a *sanitized
   dict* with no `.usage` attribute, so gating on `getattr(response, "usage")`
   silently drops usage and cost for **every gateway turn**. Fall back to the
   `usage` summary dict.

**Gateway caveat — the honest limit of this work.** The gateway surface was never
driven live. **Whether `post_api_request` fires on gateway turns at all is
unproven and must be verified on a real gateway** before anything depends on it.

## E3 — `ctx.state` and an out-of-process cron can safely share state

`ctx.state` resolves to a profile-scoped
`~/.hermes/plugin-data/agent-plugin-<slug>-<sha256(plugin_id)[:8]>/state.json`
with a 10 MiB quota.

Cross-process locking is explicit and documented in `hermes_cli/plugins.py`
(`_locked_plugin_state`): an `fcntl` lock on a **sibling** `.state.json.lock` file
(msvcrt on Windows), plus a thread lock, with atomic `os.replace`.

**Experiment.** Derived the namespace independently in a standalone script, took
the same `fcntl` lock, performed a read-modify-write, then ran an in-process
session calling `ctx.state.set()`.

| Step | Result |
|---|---|
| Derived namespace independently | **exact match** |
| Out-of-process read-modify-write under `fcntl` | succeeded; in-process marker preserved |
| In-process `set()` afterwards | out-of-process writes **survived** — no clobber |

So a two-halves architecture is viable on `ctx.state`, provided the cron half
(a) derives the namespace, (b) takes the `fcntl` lock on `.state.json.lock`, and
(c) writes atomically.

**Risk to weigh before depending on this.** `_portable_skill_namespace` is a
private, underscore-prefixed function. Depending on its exact digest scheme couples
the out-of-process half to a Hermes internal with no stability contract, and the
upstream compat suite covers *plugin APIs*, not this. Either pin and test it, or
keep the current file contract under `~/.hermes/state/revenium/`.

## E4 — `exit 2` and `fail_closed` both work

A single `hermes hooks test pre_tool_call` run with three hooks:

| Hook | Exit | Config | Dispatcher verdict |
|---|---|---|---|
| exit-2 | 2 | default | **BLOCK** — `{"action":"block","message":"…"}`, stderr used verbatim |
| crash | 7 + garbage stdout | `fail_closed: true` | **BLOCK** — "failed closed: unparseable stdout" |
| crash-open | 9 + garbage stdout | default | **fails open** — contributed nothing to the dispatcher |

Two consequences for `pre_tool_call.sh`:

- The hand-built block JSON could collapse to `exit 2` plus a stderr message —
  less code, same wire shape. **But the halt response string is contractual**
  (see the "Modifying the halt response string" anti-pattern in `CLAUDE.md`), so
  verify the stderr path reproduces it byte-for-byte before adopting.
- **`fail_closed: true` is a policy decision, not a free win.** It contradicts the
  deliberate current posture: the skill fails open when `guardrail-status.json` is
  missing, so a never-installed cron does not block all work. Fail-closed trades
  availability for enforcement integrity. For a *budget* tool that argues one way;
  for a *never-installed* tool it argues the other. Owner's call.

## Dead ends — do not chase

- **`ctx.cron` does not exist.** It appeared on an upstream tracker, but the
  shipping PR states "Excludes cron", and it is confirmed absent from
  `PluginContext`. The crontab installer cannot be retired this way.
  `ctx.spawn_task` is supervised-but-in-process — it runs only while Hermes runs,
  whereas the current cron runs regardless. Not an equivalent.
- **Capabilities/consent will not clear the security scanner.** The consent gates
  are all LLM/tool-override (`tools.override`, `llm.provider_override`,
  `llm.model_override`, `llm.agent_id_override`, `llm.profile_override`,
  `llm.task_override`). None covers filesystem, subprocess, or `os.environ` —
  which is what the DANGEROUS verdict flags. Not a path to scanner clearance.
  (The consent flow itself *does* work: enabling the probe non-interactively left
  the capability ungranted, failing closed as documented.)

## Corrections

**The gateway session-reset root cause recorded on 2026-08-13 was wrong.**

The original note asserted that a fresh v0.20.1 defaults its session-reset policy
to a mode of `none`, making gateway sessions continuous so `on_session_end`
structurally never fires. **That explanation does not hold** — the root
configuration actually sets that policy to a mode of `both`. The *observation*
(that `on_session_end` did not fire for gateway sessions) was real and was
addressed by registering `on_session_finalize` alongside a guarded `post_llm_call`,
shipped and live-proven on 2026-07-29. Only the stated cause was incorrect.

Recorded here because the wrong cause is more dangerous than no cause: it would
send a future reader to change a config knob that is not the problem — and
changing that particular knob has a real cost, since forcing a reset policy makes
conversations lose context. Rejecting that change is a standing decision in this
repository, pinned by a repository-scoped test
(`tests/test_phase29_no_session_reset_change.py`) that fails if the setting's key
appears anywhere in the shipped tree.

**Note on spelling.** This section deliberately writes the setting's name in prose
("session-reset policy") rather than as its literal underscored config key. That
guard scans every shipped file for the key, and it should stay absolute — a
documentation file is not a reason to add an exclusion to it. If you are editing
this paragraph, do not "correct" the hyphen back; you will turn the suite red.

## Disposition of the proposals this work produced

| Proposal | Disposition |
|---|---|
| **P-A** — meter auxiliary usage from `session_model_usage` | **Closed unbuilt (2026-08-15).** Its own pre-committed gate measured auxiliary spend at 0.4598% of fleet cost against a ≥1% build threshold. See `docs/auxiliary-usage-sizing.md`. Note that document also corrects P-A's ledger-key description: the live primary key is six columns, not the four assumed here. |
| **P-B** — adopt `fail_closed` / `exit 2` in `pre_tool_call.sh` | Open. Requires the policy decision in E4 first. |
| **P-C** — guardrail standing instruction as a prompt section | Open. **Hard constraint from E1: the section must not be the live-state carrier.** |
| **P-D** — event-driven metering on `post_api_request` | **Promoted** as the successor to the closed P-A phase. ⚠️ **One claim in the original proposal is refuted:** it asserted this "gets aux usage for free". It does not. A single run was directly observed to serve two chat-completions calls (one main-loop, one title generation) and emit only **one** `post_api_request` event. `post_api_request` does not fire for auxiliary calls. `session_model_usage` remains the only source for auxiliary spend. |
| **P-E** — native subagent attribution via `subagent_start`/`subagent_stop` | Deferred. The existing marker machinery shipped recently and works; this is consolidation, not a fix. |

## Verified against

Date: 2026-08-13; corrections applied 2026-08-15. Method: a throwaway probe plugin
on a dedicated test VM running Hermes v0.20.1, driven against a local
OpenAI-compatible mock so that no model spend and no production data were involved.
The runtime surface confirmed **37 hooks** in `VALID_HOOKS` and a `PluginContext`
exposing `register_system_prompt_section`, `state`, `get_config`/`set_config`,
`spawn_task`, `subagent_lifecycle`, `platform_actions`, `emit`/`subscribe`, and
`on_unload`.

Host addresses, probe file paths, service unit names, and individual session
identifiers are deliberately omitted; identifier *shapes* are retained where a
future implementation depends on them. A local development box on v0.20.0 does
**not** expose these surfaces — version-check before relying on any finding here.
