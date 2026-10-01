# Subscriber attribution: live proof (SUB-10)

This record establishes, against the reference host and a real Revenium tenant, whether the
subscriber-attribution wire dimension shipped in Phases 61-63 behaves as designed for three
arms: a `cli` session shipping no subscriber at all, a Slack session attributing spend to the
human who drove it, and a subagent session inheriting its root's actor. Verification ran on
2026-09-30. This phase observes shipped behaviour and builds no new capability.

This page covers evidence only - the live verdict for each arm, and how it was scored. For
the dimension's own design (the `<source>:<id>` key, the `subscriberEmailMode` switch and its
accepted limits, and the `subscriber-names.sh` mapping procedure), see
`docs/subscriber-attribution.md`; this record does not restate that content.

## Results

| Arm | What it tests | Induced session | Transaction id | `subscriberId` on tenant row | Verdict |
|---|---|---|---|---|---|
| Omission | A `cli` session ships no subscriber at all | `20260930_215104_debdb4` | `20260930_215104_debdb4-3303-001a0f44cfe7503a7f094a1ade555f51c` | key present, value `null` | **CONFIRMED** |
| Attribution | Per-subscriber spend appears in Revenium and attributes to the right actor | `20260930_215808_13016a29` (Slack root) | `20260930_215808_13016a29-139575-001a0f453a07697252b822cf0cf34b3bc` | key present, value `slack:<redacted-actor-id>` | **CONFIRMED** |
| Inheritance | A subagent session inherits its root's actor | `20260930_215830_b26423` (one of three subagent children of the Slack root) | `20260930_215830_b26423-12137-001a0f4539aa767a7183b2e6234045302` | key present, value `slack:<redacted-actor-id>` (byte-identical to the root row's) | **CONFIRMED** |

All three arms are scored live, from one induced arc, against one window pull
(`/tmp/sub64-window.json`, 27 rows, reference tenant). No arm is ever dropped from this table.

## How each arm was scored

CLI read-back against the tenant is the **only** admissible tenant-side evidence for any arm
in this record. No UI or dashboard observation was used, for any arm, at any point. This
mirrors the bar `docs/live-tenant-proof.md` set and `docs/live-envelope-verification.md`
reaffirmed: a CLI read-back is reproducible by a later phase and a screenshot is not.

Scoring is a **point lookup of the specific transaction**, never an aggregate showing the
dimension merely exists somewhere in the tenant's data. Each arm's claim rests on matching one
induced session's ledger-derived transaction id against one tenant-side row.

Host-side wire evidence - the argv the skill sent and the ledger line it wrote - is
**corroboration only and never sufficient on its own**, for any arm including the omission
arm. It establishes that the skill did its job, not that the platform ingested and attributed
the value correctly. This is the output-vs-outcome distinction
`docs/claim-distinctions-and-evidence-boundaries.md` already draws.

**Exit status is never evidence.** On 2026-08-19 the Revenium API returned success and
persisted nothing for roughly seven hours; `docs/live-tenant-proof.md` records that incident
as the reason scoring never rests on a `0` exit code. A `0` exit is recorded where it occurred
in this phase's own tick-completion evidence, but it carries no evidentiary weight by itself -
only the printed content of the tenant-side read counts.

## The correlation procedure, recorded

Per D-10, this phase ships no new runtime capability and no new script. The correlation
sequence below is a recorded procedure, reproducible by a future reader, not shipped surface.

1. **Get the ledger tuple for the induced session**, on the reference host:
   ```bash
   grep "^HERMES:<induced-session-id>:" ~/.hermes/state/revenium/revenium-hermes.ledger
   # -> HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>
   ```
   Two candidate transaction ids follow from this tuple: `<sid>-<total_tokens>-<muid>` for the
   marker-split completion path, and `<sid>-<total_tokens>` for the markerless path. Try the
   marker-split form first when the session carries a `.ready` sentinel.

2. **Pull a completions window as JSON**, on the reference host, with the reference host's own
   key:
   ```bash
   revenium metrics completions --from "<window-start-ISO8601>" --to "<now-ISO8601>" \
     --output json > /tmp/window.json
   ```
   `metrics completions get <id>` is **not** the right verb here - its `<id>` argument is the
   server's own short opaque row id, and passing the skill's own transaction id returns
   `HTTP 400: Failed to decode hashed Id`. There is no server-side subscriber or transaction
   filter on this endpoint; all slicing is client-side, which is why the window is pulled once
   and matched afterward rather than filtered server-side.

3. **Match client-side on `transactionId`**, trying *both* candidates from step 1 - the
   marker-split form first, then the markerless form. A session reported through the
   markerless path has no `<muid>` suffix on its row, so a lookup that only ever appends
   `<muid>` returns no match even though the tenant row exists:
   ```python
   import json
   rows = json.load(open("/tmp/window.json"))
   sid, total_tokens, muid = "<sid>", "<total_tokens>", "<muid>"   # from step 1
   candidates = [f"{sid}-{total_tokens}-{muid}", f"{sid}-{total_tokens}"]
   match = next(
       (r for c in candidates for r in rows if r.get("transactionId") == c),
       None,
   )
   ```
   Every arm in this record was scored with both candidates in hand; each one matched on the
   marker-split form, because all five induced sessions carried a `.ready` sentinel. The
   markerless candidate is kept in the procedure because it is the supported path for a
   session with no marker, not because any arm here needed it.

   The matched row's `subscriberId`, `subscriberEmail`, `source` and `taskType` are then read
   directly from the returned JSON - never inferred, never re-derived locally.

This is a **recorded procedure**, deliberately not packaged as a script (D-10). A later phase
can promote it into one if a standing need for repeated live proofs emerges.

## Omission - a cli session ships no subscriber

The induced `cli` session (`20260930_215104_debdb4`, `user_id IS NULL` in `state.db`, induced
by a single-turn, non-destructive prompt asking the agent to state the current date) shipped a
ledger line after the post-induction cron pass:

```
HERMES:20260930_215104_debdb4:3303:1790807416.591:001a0f44cfe7503a7f094a1ade555f51c
```

The marker-split transaction id built from that tuple (`<sid>-<total_tokens>-<muid>`) matched
exactly one row in the completions window pulled from the reference tenant:

```
transactionId: 20260930_215104_debdb4-3303-001a0f44cfe7503a7f094a1ade555f51c
subscriberId key present: true
subscriberId value: null
subscriberEmail value: null
taskType: current_date_inquiry
```

The `subscriberId` key is present on the row - not omitted - and its value is `null`. Per
D-13, this is precisely the CONFIRMED case: the omission is distinguishable as "field present,
value empty," not "field absent from the schema entirely."

**The discriminating control for this arm**, read from the same window pull: the Attribution
row below - the Slack root session (`20260930_215808_13016a29`) - and the Inheritance row - one
of its three subagent children (`20260930_215830_b26423`) - both carry
`subscriberId: "slack:<redacted-actor-id>"`, present and non-null, returned by the identical
`metrics completions` verb, from the identical window pull, against the identical tenant, in
the identical pass as this row. The `cli` row's null value is therefore read against a real,
same-pull, non-null control, not merely asserted in isolation: 19 of the window's 27 rows read
null and 8 read non-null, so the field demonstrably discriminates rather than reading null for
everyone. This rules out "the field is always null" as an alternative explanation for the
omission arm's result.

**Omission verdict: CONFIRMED**

## Attribution - per-subscriber spend attributes to the right actor

The induced Slack root session (`20260930_215808_13016a29`, driven by a real human over Slack
- see `64-02-SUMMARY.md` for the induction message and reply) shipped a ledger line after the
same post-induction cron pass the omission arm used:

```
HERMES:20260930_215808_13016a29:139575:1790807414.274:001a0f453a07697252b822cf0cf34b3bc
```

The marker-split transaction id built from that tuple (`<sid>-<total_tokens>-<muid>`) matched
exactly one row in the same `/tmp/sub64-window.json` completions window pulled from the
reference tenant (the tenant `64-02-SUMMARY.md` confirmed by `revenium config show`
plus `revenium tenants get` on this same host - named in that SUMMARY only, never published):

```
transactionId: 20260930_215808_13016a29-139575-001a0f453a07697252b822cf0cf34b3bc
subscriberId key present: true
subscriberId value: slack:<redacted-actor-id>
subscriberEmail value: null
source: metering-source object (label "Default") - the tenant's ingestion source, distinct
  from the session's own `slack` source family
taskType: signup_pipeline_failure_subagent_dispatch
agenticJobId: signup_pipeline_sqlite_fix_0266
```

`subscriberEmail` reads `null` here, as expected: the email flag ships only for the `email`
source, and this session is Slack-sourced. No unexpected non-null value was observed.

**Three-way agreement, confirmed byte-for-byte:**

1. The session's own row in the host's `state.db` carries `user_id` = the raw Slack actor id
   (quoted, unredacted, in `.planning/phases/64-live-proof/64-03-SUMMARY.md` only).
2. The deployed `hermes-report.sh`'s own wire evidence, read directly from
   `revenium-metering.log` for this exact session and both its markers:
   ```
   Reported: session=20260930_215808_13016a29 ... subscriber=slack:<redacted-actor-id>
   ```
3. The tenant row's `subscriberId`, read back above: `slack:<redacted-actor-id>`.

All three carried the identical value. The namespaced shape (`slack:` prefix, per
`resolve_subscriber_id` in `skills/revenium/scripts/common.sh`) matches the session's own
`user_id` exactly, confirming the wire-pair chokepoint and the tenant's stored value agree end
to end - not merely that a subscriber value exists, but that it is the *right* one.

**This row is also the discriminating control the omission arm cites above**: a non-null
`subscriberId`, from the same read verb, the same window pull, the same tenant, ruling out
"the field is always null" as an explanation for the omission arm's result.

**Attribution verdict: CONFIRMED**

## Inheritance - a subagent session inherits its root's actor

Three `source='subagent'` children were induced under the Slack root in the same turn (see
`64-02-SUMMARY.md`); this arm scores one of them, `20260930_215830_b26423`. Its ledger line
from the same post-induction cron pass:

```
HERMES:20260930_215830_b26423:12137:1790807411.184:001a0f4539aa767a7183b2e6234045302
```

The marker-split transaction id matched exactly one row in the same `/tmp/sub64-window.json`
window, against the same reference tenant:

```
transactionId: 20260930_215830_b26423-12137-001a0f4539aa767a7183b2e6234045302
subscriberId value: slack:<redacted-actor-id>
agenticJobId: signup_pipeline_sqlite_fix_0266
parentTransactionId: (not present on this row)
taskType: terminal_echo_probe_check
```

The wire evidence in `revenium-metering.log` corroborates the same value was sent for this
child session's both markers:
```
Reported: session=20260930_215830_b26423 ... subscriber=slack:<redacted-actor-id>
```

**The claim this arm establishes is a comparison, not a value.** The child row's
`subscriberId` was compared byte-for-byte against the root row's `subscriberId` (scored in the
Attribution section above): both read `slack:<redacted-actor-id>`, and the comparison returned
equal.

**Equality alone would not establish inheritance** - a child that resolved its *own* identity
to the same actor would produce the identical row. Two further read-only observations against
the reference host rule that out, and are what make this verdict auditable:

1. **The child has no identity of its own.** A direct `state.db` read of the child's own
   session row returns a null `user_id`, so there was nothing for `resolve_subscriber_id` to
   resolve independently:
   ```
   20260930_215808_13016a29|slack|<redacted-actor-id>   <- root
   20260930_215830_b26423  |subagent|<NULL>             <- child, no user_id of its own
   ```
2. **The parent link is resolved by the root-walk itself**, not asserted:
   ```bash
   python3 ~/.hermes/skills/revenium/scripts/get-root-session-id.py 20260930_215830_b26423
   # -> 20260930_215808_13016a29
   ```
   This is the same `get-root-session-id.py` the reporter calls, returning the same root whose
   row was scored in the Attribution section - so the child's key demonstrably came from that
   root and not from somewhere else.

Together: the child had nothing of its own, the root-walk links it to this specific root, and
its shipped key is byte-identical to that root's. The child inherited its root's actor exactly,
through the existing root-walk, with no divergence.

`revenium squads get` was **not** used to score this arm. Research (`64-RESEARCH.md` RQ-4)
probed both the root session id and a subagent child id on this host and both returned
`Resource not found` - the squad entity requires deliberate squad-dimension configuration that
this induced arc never set, so a 404 there would be an artifact of squad configuration, not
evidence about inheritance. The `metrics completions` transactionId-match used for the other
two arms is the correct instrument here and is what this arm used.

Three subagent children were available from the induced arc
(`20260930_215830_b26423`, `20260930_215830_15a289`, `20260930_215830_b7a9db`); one was scored.

**This arm establishes positive inheritance only.** Phase 61's D-11 negative-inheritance arm -
a `cron` child inheriting nothing - is not re-proven live here; it is already pinned in the
test suite and established by measurement on that host (D-15).

**Inheritance verdict: CONFIRMED**

## What this does not establish

1. **One host, one tenant, one cron pass.** Nothing here establishes behaviour on a
   multi-profile host, across tenants, or across repeated cron passes. Every arm was read
   back from the same single pass, against the same single tenant.
2. **One induced arc per arm.** The attribution and inheritance arms come from a single
   Slack-driven arc - one root session and three subagent children; the omission arm from a
   single `cli` session. These are existence proofs, not measurements of a rate.
3. **CLI read-back only.** No dashboard or UI observation contributed to any verdict, per
   D-01. The record therefore establishes what the API returns, not what an operator sees
   rendered in the product.
4. **Host-side wire evidence is corroboration only.** That the skill sent the argv carrying
   `--subscriber-id` and wrote the ledger line establishes that the skill did its job; it does
   not establish that the platform ingested or attributed the value. Only the tenant read
   scores an arm, per D-03.
5. **Omission covers `cli` only, not `cron`.** `cron` is the larger unattributed population on
   this host but arrives on its own schedule and was neither induced nor read back here; SUB-10
   asks for `cli`, per D-14.
6. **Positive inheritance only.** Phase 61's D-11 negative-inheritance arm - a `cron` child
   inheriting nothing - is not re-proven live here; it is already pinned in the test suite, and
   Phase 61 established by measurement that inheritance is additive on this host, per D-15.
7. **The Slack-triggers-subagents pattern's reproducibility, and how it was induced.** It took
   exactly one induction attempt on this host (`64-02-SUMMARY.md`, Task 1: "Attempts: 1."),
   answering research Open Question 1 affirmatively for this host. But the induction message
   explicitly named the delegation toolset and asked for three parallel subagents by name,
   rather than relying on organic fan-out - unlike the two historical precedents research
   observed (2026-09-20, 2026-09-02), which were organic. The actor requirement (D-07: a real
   human over Slack) holds regardless of how the fan-out was requested; what is not
   established is that this exact fan-out pattern recurs unprompted, only that it can be
   produced on request. This is the phase's one medium-confidence assumption.
8. **Nothing about spend accuracy or cost attribution.** These arms establish that an identity
   dimension is carried on the wire and read back correctly; they say nothing about whether the
   token or cost figures on those same rows are themselves correct.
9. **No arm in this record scored NOT CONFIRMED.** All three arms - omission, attribution, and
   inheritance - scored CONFIRMED. None remains open, and none required a fallback read.

## The environment

- **Deployed commit:** `5e200d67d8f7f6cf04de8de1cee3b1e5fc6c9fe2`, deployed to the reference
  host's skill tree and proven byte-identical across all 58 committed paths (see
  `.planning/phases/64-live-proof/64-01-SUMMARY.md`).
- **Host:** the reference host used throughout the Subscriber Attribution milestone's
  measurements. Named by role only - no address, no hostname, no ssh key name.
- **CLI:** `revenium v1.7-5-g8d46ad4 (8d46ad4)`, confirmed on the reference host.
- **Run date:** 2026-09-30.
- **Measured cron pass duration:** 17m22s for the completion-metering stage that shipped all
  five induced sessions and whose resulting tenant rows this record scores (22:30:06 UTC to
  22:47:28 UTC), per the `revenium-metering.log` bracket `64-02-SUMMARY.md` captured.
- Neither a credential value nor a tenant identifier appears anywhere in this file.

---
*Phase: 64-live-proof*
*Recorded: 2026-09-30*
