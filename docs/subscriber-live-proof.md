# Subscriber attribution: live proof (SUB-10)

This record establishes, against the reference host and a real Revenium tenant, whether the
subscriber-attribution wire dimension shipped in Phases 61-63 behaves as designed for three
arms: a `cli` session shipping no subscriber at all, a Slack session attributing spend to the
human who drove it, and a subagent session inheriting its root's actor. Verification ran on
2026-09-30. This phase observes shipped behaviour and builds no new capability.

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

3. **Match client-side on `transactionId`:**
   ```python
   import json
   rows = json.load(open("/tmp/window.json"))
   target = "<sid>-<total_tokens>-<muid>"   # from step 1
   match = [r for r in rows if r.get("transactionId") == target]
   ```
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
equal. The child inherited its root's actor exactly, through the existing root-walk
(`skills/revenium/scripts/get-root-session-id.py`), with no divergence.

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

## The environment

- **Deployed commit:** `5e200d67d8f7f6cf04de8de1cee3b1e5fc6c9fe2`, deployed to the reference
  host's skill tree and proven byte-identical across all 58 committed paths (see
  `.planning/phases/64-live-proof/64-01-SUMMARY.md`).
- **Host:** the reference host used throughout the Subscriber Attribution milestone's
  measurements. Named by role only - no address, no hostname, no ssh key name.
- **CLI:** `revenium v1.7-5-g8d46ad4 (8d46ad4)`, confirmed on the reference host.
- Neither a credential value nor a tenant identifier appears anywhere in this file.

---
*Phase: 64-live-proof*
*Recorded: 2026-09-30*
