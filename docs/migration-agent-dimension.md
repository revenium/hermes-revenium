# Migrating to Root-Inherited Agent Attribution (v1.4)

This guide covers two changes shipped together in the v1.4 release: how `--agent`
is resolved on zero-marker (subagent) completions, and the three new squad
attribution flags. The first half is a code change with **no observable effect**
on any current install; the second half is new, observable behavior. Both are
covered here because they touch the same emit paths in
`skills/revenium/scripts/hermes-report.sh`.

## The AGENT dimension: nothing changes

Before v1.4, a subagent session with no marker file reported `--agent` as a
hardcoded read of `REVENIUM_AGENT_NAME`. As of v1.4, that same completion
resolves `--agent` through the session's root — a subagent inherits the agent
name of the root session that dispatched it, via the same once-per-session
`root_agent_name` resolution the squad flags below already use.

**The emitted value is identical on every current install.** No code path in
this skill has ever written an `agent` field into a marker record — not
`_write_marker_pair`, not `_write_job_marker`. Root-inherited resolution
therefore falls back to `REVENIUM_AGENT_NAME` exactly as before, for every
session, on every install, today.

Concretely, this means:

- **Saved Revenium views keyed on AGENT need no change.**
- **`AGENT:IS:` guardrail filters** (see `scripts/common.sh:26`) keep matching
  exactly the sessions they matched before.
- **There is no migration step to perform.** This section exists to document
  the absence of change, not to prescribe one.

**What would invalidate this.** If a future change adds an `"agent"` key to
`_write_marker_pair`'s record closure or `_write_job_marker`'s record dict in
`classifier.py`, root inheritance begins producing genuinely different
per-subagent values, and this section must be rewritten. The test that
enforces this today is `tests/test_phase29_agent_inheritance.py` — its
byte-diff test compares captured argv against a golden fixture and goes red
the moment a markerless completion's `--agent` value stops matching
`REVENIUM_AGENT_NAME`.

## Squad grouping: three new fields do appear

This is the observable half of the release. Every metered completion — marker-
bearing or markerless — now carries three additional flags when the installed
`revenium` CLI supports them (older CLIs see no change; the flags are omitted
entirely):

| Flag | Value |
|------|-------|
| `--squad-id` | The root session's id — the same session that dispatched every subagent hanging off it. |
| `--squad-name` | The root's agent name, falling back to `REVENIUM_AGENT_NAME` for the same reason `--agent` does today — never emitted empty. |
| `--squad-role` | The literal string `root` for the root session itself, `subagent` for every session dispatched from it. |

**This vocabulary is topology, not function.** `--squad-role` describes where a
session sits in the dispatch tree, not what it did (`planner`, `executor`,
`reviewer`, etc.). Function-derived roles were deliberately deferred rather
than shipped now and migrated later — topology is derivable from the existing
root-walk with no marker dependency, so it is available on every session,
whereas a functional label would degrade to a fallback exactly when markers
are missing.

**Availability.** The three flags appear only when the installed `revenium`
CLI advertises support for them (v1.3.0 and newer). An older CLI continues to
meter exactly as it did before this release — no missing-flag errors, no
behavior change on the wire.

## Hook registration: three triggers, one wider source set

As of v1.4, the `revenium-classifier` plugin registers three hooks
(`__init__.py:308-310`, mirrored in `plugin.yaml:4-7`):

- `on_session_end` — the pre-existing hook, unchanged.
- `on_session_finalize` — new in v1.4, the session-boundary trigger.
- `post_llm_call` — new in v1.4, the per-turn trigger.

Before this release, exactly one of the three fired: `on_session_end`.

**The practical effect: interactive gateway session conversation content now
reaches the auxiliary classifier LLM.** Before this release, in practice only
the scheduled `cron_*` sessions' content reached it — interactive gateway
sessions never fired any hook at all. `_read_session_messages` (called at
`classifier.py:1079`) and `_read_session_transcript` (called at
`classifier.py:1106`) are the two readers that carry that content into the
classification call, for every session kind alike; what changed is which
session kinds now reach them.

**Same destination, same data category — a wider source set.** This is not a
new data-sharing behavior, a new egress, or a new recipient: the auxiliary LLM
is the same auxiliary LLM, and conversation content is the same data category
it always sent. What changed is which sessions feed that existing flow.
Unlike the AGENT dimension above, this is a real change to disclose, not an
absence of one — an operator with a data-handling policy needs to know the
source set widened.

**Bounded to one inference per session.** Classification happens at most once
per session, not once per turn. `_session_already_classified`
(`classifier.py:648-677`) is a permanent latch consulted at a single call site
inside `run_classification_async` (`classifier.py:1063`) that every trigger
flows through, in every firing order — so adding two more triggers did not
add inferences. A session of N turns costs one classification inference, not
N.

## Where to look if you build on this

- `tests/test_phase29_agent_inheritance.py` is the test suite that keeps the
  "no observable change" claim honest. If it ever fails, this document's first
  half is what needs updating.
- `scripts/common.sh:26` documents `REVENIUM_AGENT_NAME` and the
  `--filter AGENT:IS:${REVENIUM_AGENT_NAME}` guardrail convention this release
  does not disturb.
- If you build a saved view or a guardrail filter on `--squad-role`, the two
  values you will see are `root` and `subagent` — no other values are emitted
  by this release.
