# Subscriber Attribution

[← Documentation index](README.md)

Every metered completion this skill ships can carry a `--subscriber-id` naming the
actor who drove it: the person, bot or app interacting with Hermes, not the
session, job or squad. This page documents the dimension itself, the email switch
that governs its one PII-bearing field, the limits of "obfuscated" mode, how to
turn a shipped id back into a human name and the corrected record of why that last
step is a mapping procedure rather than Revenium subscriber provisioning.

## The dimension

The actor comes from `sessions.user_id` in `state.db`, resolved by
`resolve_subscriber_id` (`common.sh`): never from `display_name`. On the
reference host, 146 of 275 Slack rows hold the *channel* id in `display_name` and
98 more are empty; falling back to it would label spend with channel names instead
of people. The human label, where one exists, is
`json_extract(origin_json,'$.user_name')`, which `subscriber-names.sh` reads
separately (see "Mapping an id back to a human" below): it is never used to
resolve the wire id itself.

The resolved value is namespaced `<source>:<id>` (`slack:U02C12JG78F`,
`email:jane@corp.example`, `webhook:spike-test`) so two platforms can never collide
and the source stays legible without a join. A subagent session inherits its
root session's actor through the same root-walk that already resolves
`--agentic-job-id` and the squad dimensions, so subagent spend is never
unattributed just because the subagent itself carries no identity. Bot and app
actors are attributed identically to humans, with no special casing: on the
reference host the largest Slack spender by cost is an app, not a person and
that is accepted deliberately.

A session with no resolvable actor (`cli`, `cron`, `tui` and any source
lacking both `user_id` and `origin_json`) ships no subscriber flags at all
and meters byte-identically to how it did before this dimension existed. On the
reference host that is 97% of sessions and 92% of cost; the golden argv fixtures
pin this absence as an exact-list equality, not a best-effort omission.

The dimension is carried by all four `meter completion` emission sites, not a
subset: wiring a subset was the failure mode this project's own SUB-05
requirement exists to prevent:

- `hermes-report.sh`'s markerless completion site
- `hermes-report.sh`'s marker-split completion site
- `hermes-report.sh`'s auxiliary-usage pass (`report_auxiliary_usage`)
- `api-event-report.sh`'s per-record event site

Every one of the four is capability-probed (`SUBSCRIBER_CLI_CAPABLE`,
`SUBSCRIBER_EMAIL_CLI_CAPABLE`) and fails open: an older `revenium` CLI that
does not advertise `--subscriber-id`/`--subscriber-email` on `meter completion`
meters exactly as it did before either flag existed.

## The email switch

The `email` source additionally ships `--subscriber-email`, plaintext by default,
governed by one two-value switch:

| Setting | Values | Default |
|---|---|---|
| `subscriberEmailMode` (`config.json`) | `plaintext` \| `obfuscated` | `plaintext` |
| `REVENIUM_SUBSCRIBER_EMAIL_MODE` (environment) | `plaintext` \| `obfuscated` | — |

The environment variable takes precedence over `config.json` when both are set,
following the same `resolve_switch_setting` precedent as `eventMeteringMode` and
`auxMetering`. An unrecognised value in either place falls back to `plaintext`
with exactly one warning per run: never a hard failure and never a silent
substitution the operator can't see in the log.

**The switch covers the `email` source only.** A Slack member id
(`slack:U02C12JG78F`) and a webhook token ship byte-identically in both modes,
in both `--subscriber-id` and the (never-present, for non-email sources)
`--subscriber-email` field. This is deliberate, not an oversight: obfuscating a
Slack id would fight the mapping procedure documented below, whose entire job is
making ids resolve back to humans and email is the field Revenium's own
documented posture treats as the critical PII surface. Do not read the setting's
name as blanket coverage: flip it and a Slack actor's id is exactly as legible
in the metering log and on the wire as it was before.

## What "obfuscated" means, and what it does not achieve

With the switch set to `obfuscated`, an email-source actor's `--subscriber-id`
becomes `email:` followed by the untruncated, lowercase, hex SHA-256 digest
of the address, with the `email:` namespace preserved. `--subscriber-email` is
**omitted entirely**: never populated with the digest, because a hash is not a
reachable address and Revenium's email field means "a reachable address." The
id column stays a stable key either way, so per-person analytics keep working;
only the specific PII value changes.

The hash is unsalted. This is deliberate: the same address hashes to the
same key on every host, every fleet profile and after every reinstall, with no
new state to lose (this skill writes nothing new under `STATE_DIR` to support
it). An unsalted hash of an email
address can be reversed by dictionary lookup for any address an attacker can guess: run
the same SHA-256 over a list of likely addresses and a match reveals the
original. This defeats casual inspection of a dashboard and bulk scraping
across a whole export, because neither of those starts from a guessed address.
It does not defeat a targeted dictionary lookup against one specific,
guessable address. A stored per-install salt was considered and rejected: the
salt must survive every reinstall or each actor gets a new key and a ten-profile fleet would need every host to hold the
*same* salt or the fleet fragments by profile: trading one documented limit
for a worse, operationally fragile one.

**Flipping this switch on an install that has already metered fragments every
email-source actor into two permanent keys.** The plaintext key lives on every
row already sent; the hash lives on every row sent from the moment of the flip
onward. Neither set of rows can be amended or deleted (Revenium metering is
append-only) and the two keys are, in reality, the same person, with nothing
on the Revenium side to say so. This is accepted rather than prevented: an
install-time-only switch that refused a mid-life flip was offered and declined,
in favor of disclosing the fragmentation instead. Both reporters
(`hermes-report.sh` and `api-event-report.sh`) call a shared helper,
`warn_subscriber_mode_flip_once`, that emits exactly one warning the first time
either script observes a mode different from the install's previously observed
one, rate-limited through a sentinel directory so it never repeats on
subsequent ticks. The warning names the fragmentation and states plainly that
neither key set can be amended.

## Mapping a shipped id back to a human

`meter completion` has no `--subscriber-name` flag under any spelling: the
wire carries a stable key and nothing more. Turning `slack:U02C12JG78F` back
into a person is not something Revenium's API does for you; this skill ships a
read-only, human-invoked script for it instead:

```
skills/revenium/scripts/subscriber-names.sh [--quiet] [--profile PROFILE]
```

It walks every profile home on the host by default (`hermes_profile_homes`,
default home first), because a fleet host commonly runs one gateway per profile
with entirely separate state: a script that only checks `$HERMES_HOME` would
look empty on a fleet host even when every profile has actors to name.
`--profile <name>` restricts it to one home. It opens each home's `state.db`
`mode=ro`, resolves each actor's id through the same `resolve_subscriber_wire_pair`
chokepoint every emission site uses (so the ID column shows exactly the form
that ships: plaintext or `email:<64-hex>`) and pairs it with the name
recorded at `json_extract(origin_json, '$.user_name')`. The mode is resolved
**per profile**, not once for the whole host: each profile home's own
`config.json` (or, for the default profile, the process's own environment)
governs the form shown for that profile's actors, exactly as each profile's
own `hermes-report.sh`/`api-event-report.sh` reporter does: a fleet-wide run
can legitimately show one profile's email-source actors in plaintext and
another's in `email:<64-hex>` in the same table, because that is what each
profile's own reporter ships.

**Exit codes are stable for scripting:**

| Exit | Meaning |
|---|---|
| `0` | every resolved subscriber id (an actor whose id ships) has at least one name |
| `10` | at least one resolved subscriber id has no name |
| `1` | could not determine: no inspected home had a readable `state.db` with a `sessions` table |

**The marker tokens it prints, quoted exactly as shipped:**

| Marker | Meaning |
|---|---|
| `UNRESOLVED:no-name-recorded` | the actor resolved to an id, but no name was ever recorded for it |
| `UNRESOLVED:no-origin_json-column` | this home's `sessions` table has no `origin_json` column at all |
| ` [AMBIGUOUS]` (suffix) | this actor has recorded two or more distinct names; both are shown |
| ` [ALTERED]` (suffix) | the recorded name contained a transport control character, replaced with `?` before it ever left the query |
| `NO-ID:rejected` | the actor's `source`/`user_id` pair failed `resolve_subscriber_id`'s own safety check |
| `NO-ID:unsafe` | the raw `source` or `user_id` itself was transport-unsafe; no raw bytes are ever printed for this actor, only its session count |

**Its output is identity data about named individuals and it is deliberately
unmasked**: resolution is this script's entire purpose, so masking the output
would defeat it. It never writes to `revenium-metering.log`; every line goes to
stdout only and a run's success, empty result or failure leaves the log
byte-identical. That is also why this script's output is not the artifact
to paste into a support ticket. `diagnose.sh`'s output explicitly is the
support-ticket artifact; `subscriber-names.sh`'s output explicitly is not and
the two must not be confused in either direction: one exists to be shared
outside the operator's own terminal, the other exists specifically so it is
never shared that way.

An actor whose name cannot be resolved is listed and marked, never omitted.
An operator who sees twelve clean-looking names and has no way to tell that nine
more actors are spending unattributed has been misled by the report, not
informed by it: the same silent-gap failure this project has hit before with
dropped auxiliary spend and long-lived markerless sessions. The name is also
**never backfilled from `display_name`**, for the same reason the dimension
itself never resolves from it (see "The dimension" above): doing so would
relabel real spend with channel names on this host's Slack traffic.

## The CLI gap, and the corrected record

`meter completion --help` advertises `--subscriber-id` and `--subscriber-email`
but no `--subscriber-name` under any spelling: confirmed live, so the
mapping script above, not a wire field, is what closes this gap. Revenium
subscriber provisioning (`revenium subscribers create`) was considered and
rejected as the alternative and the roadmap's earlier record of *why* it was
rejected was wrong in a way worth correcting plainly here.

**Verified live, 2026-09-28, `revenium 1.5.0 (0f5f3a7)`, tenant `aL7ZRO2`,** by
running the probes below and reading exactly what they printed:

- `revenium subscribers list` → HTTP 403, `{"error":"Access denied..."}`.
- `revenium subscribers lookup --email <address>` → HTTP 404,
  `{"error":"Resource not found."}`.

That second result is the correction: the lookup verb is permitted (there
is simply no matching subscriber for the addresses probed) while only the
**list verb** is denied. Earlier tracked records in this repo attributed the
whole provisioning block to the list-verb permission denial; that was only half
true. The real block on closing SUB-09 by provisioning Revenium subscriber
entities is that `revenium subscribers create` requires `--email` as a
**required** flag and Slack actors have no email anywhere in this project's
`state.db`: meeting the requirement that way would mean fabricating an
address, which this repo refuses to do. `subscribers create` was not
exercised against the live API for this record: it was probed only with
`--dry-run`, which does not reach the API and is a known false-green on this
CLI (the same false-green class that produced a wrong verdict on the ROI
outcome-metrics append path). So this record states plainly what it does and
does not establish: the list/lookup split above is live-verified; whether
`subscribers create` would actually succeed with a real email is not
verified here and is moot regardless, since no email exists to try it with.

SUB-09 is therefore met by `subscriber-names.sh`'s documented mapping
procedure, not by provisioning: a decision that also keeps this skill from
taking on a posture it has never had, writing entities into a Revenium tenant.
