# Halt enforcement — live verification against a real breached rule

*Phase 19 SC-8. Kept in `docs/` deliberately: `.planning/` is gitignored, so a
finding recorded only there does not survive.*

**Date:** 2026-08-19 · **Verdict: PASS**, with two defects found.

## Why this run existed

19-12 already recorded "SC-8 MET" on the Mac Studio, and ROADMAP checks it off.
That run drove the hooks against **synthetic `guardrail-status.json` fixtures**
(19-12-SUMMARY.md line 98). The path from *Revenium reports a rule in BLOCK* →
`guardrail-check.sh` detects the transition → hooks enforce had **never run on
real API data**. That gap is what STATE.md's deferred item described, and it is
what this run closes.

## Method

Disposable rule rather than the production one. The only live rule is `5rNkE5`
($10/day TOTAL_COST, AGENT=Hermes-coder); breaching it would have cost $10 and
blocked the real coder agent.

    id 5j6jj5 · TOKEN_COUNT · DAILY · warn 100 / hard 200
    action BLOCK · shadowMode FALSE · AGENT IS Hermes-sc8probe

`--metric-type TOKEN_COUNT` on purpose: TOTAL_COST is unreliable here because of
the pricing drift in BACK-2676 — cost could derive to $0 and never breach.

Note: `budget-rules create` returned **shadowMode=true** despite `--enabled` and
no `--shadow-mode`. `budget-rules update` cannot toggle it. Rule was deleted and
recreated with an explicit `--shadow-mode=false`. **A shadow rule would have made
this whole verification vacuous** — check that field on any future rule.

Run against an isolated `REVENIUM_STATE_DIR`, using the **repo** scripts (the
deployed copy at `~/.hermes/skills/revenium/` is stale). Real local state never
touched — verified after teardown.

## Results

| stage | expected | observed |
|---|---|---|
| baseline, no usage | ok, not halted | `halted=false`, rule absent from API until first usage |
| meter 110 tok | warn band | API `warnBreached=true`; `state=warn`, `halted=false` ✅ |
| `pre_llm_call` in warn | stderr warn, no directive | one warn line, stdout `{}` ✅ |
| meter 110 more (220/200) | breach | API `breached=true`, `currentValue=220` ✅ |
| `guardrail-check.sh` | NEW ok→block halt | `halted=true`, `haltedAt` set, `haltedRule` populated with live values ✅ |
| enforcement event | embedded from API | `EVENT_SUMMARY=Rule: SC-8 Probe … Action: BLOCK …` — **AUDIT-02 on real data, first time** ✅ |
| notification | suppressed | `"halted but no notification channel configured"` — correctly gated on notifyChannel+notifyTarget, separate from autonomousMode ✅ |
| `pre_llm_call` in block | verbatim directive | exact D-01 string, real values `220 of 200` ✅ |
| `pre_tool_call` in block | blocked | `{"action":"block", …}` ✅ |
| `clear-halt.sh` | halted=false | cleared, both hooks returned `{}` ✅ |

## DEFECT 1 — the warn rate-limit is defeated when session_id can't be resolved

`pre_llm_call.sh:65-84` ignores the hook payload's `session_id` and scans
`${HERMES_HOME}/sessions/` for the newest `session_*.json`. When that yields
nothing it returns **`unknown-<unix_seconds>`**. That key changes every second,
so the `.warn` sentinel never matches.

Measured: 4 warn-band calls → **4 warn lines and 4 sentinel files**
(`unknown-1787162298__5j6jj5.flag`, `…314…`, `…316…`, `…318…`).

The code's own comment says "session_id is often empty in the hook payload", and
this host has `~/.hermes/sessions/` present with **0** session files — so the
fallback is not exotic. Consequence: in the warn band the agent gets a stderr
warn on **every LLM call**, plus one leaked sentinel file per call, GC'd only by
the manual `prune-markers.sh`.

This is precisely the failure the sentinel directory exists to prevent —
CLAUDE.md: "the `.warn` … directories exist because an ungated per-tick warn
produced millions of log lines."

## DEFECT 2 — `clear-halt.sh` gives ~one tick of relief while the rule is still breached

The halt string tells the operator "To resume: `clear-halt.sh`". Measured: after
a successful clear, the **next** `guardrail-check.sh` tick re-detects ok→block
and re-halts.

    tick 1: new-halt-transition=1  halted=True
    tick 2: new-halt-transition=0  halted=True
    tick 3: new-halt-transition=0  halted=True

Correctly **not** per-tick spam — carry-forward works, so it is one fresh halt
(and one notification) per clear, not per tick. But with a per-minute cron and
the underlying usage unchanged, "resume" lasts until the next tick unless the
window rolled or usage dropped. There is no acknowledgement or suppression
window, so the instruction in the halt string overpromises.

Neither defect is a regression from this phase; both are pre-existing and only a
real-breach run surfaces them.

## Teardown

Probe rule deleted (only `5rNkE5` remains). Real `~/.hermes/state/revenium/`
verified unchanged — no `config.json`, no `guardrail-status.json`. Repo clean.

**Permanent, unrecoverable:** 2 metered rows, 220 tokens, agent
`Hermes-sc8probe`, task-type `sc8_probe` (D-08 — rows cannot be un-sent).
