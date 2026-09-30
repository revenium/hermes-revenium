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
| Attribution | Per-subscriber spend appears in Revenium and attributes to the right actor | `20260930_215808_13016a29` (Slack root) | not yet read | not yet read | NOT CONFIRMED - read-back not yet performed |
| Inheritance | A subagent session inherits its root's actor | `20260930_215830_b26423` (one of three subagent children of the Slack root) | not yet read | not yet read | NOT CONFIRMED - read-back not yet performed |

The attribution and inheritance rows are scored by plan 64-03, which reuses the same window
pull this plan performs. No arm is ever dropped from this table.

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

**The discriminating control for this arm**, read from the same window pull: every row
belonging to the Slack root session induced alongside this one (`20260930_215808_13016a29`)
and all three of its subagent children carries `subscriberId: "slack:<redacted-actor-id>"` -
present and non-null - in that identical window. The `cli` row's null value is therefore read
against a real, same-pull, non-null control, not merely asserted in isolation. (Those rows'
own formal scoring as the attribution and inheritance arms is plan 64-03's job; they are cited
here only as the omission arm's corroborating control, per this plan's own instruction.)

**Omission verdict: CONFIRMED**

## Attribution - per-subscriber spend attributes to the right actor

Scored in the section above once its read-back lands (plan 64-03 performs and records this
arm's own scoring, reusing the same window pull Task 2 of this plan produces).

## Inheritance - a subagent session inherits its root's actor

Scored in the section above once its read-back lands (plan 64-03 performs and records this
arm's own scoring, reusing the same window pull Task 2 of this plan produces).

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
