# Live envelope verification (LIVE-01)

Whether the bounded `--metadata` envelope shipped in phases 42 and 46 is
accepted by a real Revenium API, established against a live tenant on
2026-08-29 rather than against fixtures.

**Verdict: accepted.** Five payloads were sent. All five were accepted and all
five were echoed back byte-exact. There was no rejection, no server-side
truncation, and no indeterminate result.

Phase 52 may plan against envelope acceptance as a confirmed fact, within the
limits recorded under "What this does not establish" below.

## How each arm was scored

By read-back, never by exit status. Every arm was written with
`revenium jobs outcome --metadata`, then read back with
`revenium jobs outcome-history <job-id> --output json` and corroborated with
`revenium jobs get`.

All five writes returned exit 0. That was treated as carrying no information.
On 2026-08-19 this API accepted writes and persisted nothing for roughly seven
hours while returning success, so a zero exit status is not evidence that a row
exists. An arm counted as accepted only when the server returned the row and
echoed the payload.

The shed algorithm was not reimplemented for this run. `_METADATA_CEILING_BYTES`,
`_VALUE_FAMILY_META_KEYS`, `_PROVENANCE_FAMILY_META_KEYS`, and the two-tier pop
loop were taken verbatim from `skills/revenium/scripts/hermes-report.sh`
(`:3619-3640` and `:3948-3962`), so the behaviour measured is the behaviour
that ships.

## Results

| Arm | Pre-shed bytes | Post-shed bytes | `metadata_truncated` sent | Echoed bytes | Keys returned | Outcome |
|-----|---:|---:|---|---:|---:|---------|
| A   | 337 | 337 | absent | 337 | 12 | accepted |
| B   | 4484 | 220 | `true` | 220 | 7 | accepted |
| C1  | 6157 | 3149 | `true` | 3199 | 7 | accepted; arm invalid, see below |
| C1b | 8210 | 91 | `true` | 91 | 3 | accepted |
| C2  | 4350 | 4350 | absent | 4350 | 2 | accepted |

Arms A, B, C1 and C2 were sent between `2026-08-29T15:21:22Z` and
`2026-08-29T15:21:23Z`. Arm C1b was sent at `2026-08-29T15:22:17Z`. The
read-back gate that preceded them ran at `2026-08-29T15:14:06Z`.

**Arm A — under the ceiling.** All twelve keys and the sentinel value came
back. `metadata_truncated` was correctly absent.

**Arm B — tier 1 only.** Driven over the ceiling by a value-family key. The
value family was removed, and `metadata_truncated: true` was returned *by the
server*, not merely computed locally.

**Arm C1b — both tiers.** `assumptions` (tier 1) and `study_id` (tier 2) were
both removed and three keys survived, with the marker set.

**Arm C2 — the regression check.** Driven over the ceiling by `source`, a key
in neither shed family, so both pop loops removed nothing. The marker stayed
absent, which is what the current implementation requires. An earlier version
set the marker unconditionally in this situation, producing a false signal on a
record that had dropped nothing; that defect does not reproduce against the
live server.

## An arm that did not test what it was designed to test

Arm C1 was intended to exercise both shed tiers. It did not. `assumptions` at
3000 bytes was on its own enough to bring the payload from 6157 to 3149 bytes,
under the ceiling, so tier 2 never ran and `study_id` survived. C1 is a valid
tier-1 observation and a duplicate of arm B; it is not the two-tier case.

This was caught by comparing the echoed key set against the arm's design
rather than by trusting the arm's label — `study_id` was present in the
read-back when the design required it to be gone. The arm was re-sent as C1b
with `study_id` at 5000 bytes, so that the provenance family alone still
exceeds the ceiling once tier 1 has run.

C1 is retained in this record rather than removed. A mis-sized arm quietly
dropped from the table would be the more misleading artifact.

## The 4096-byte ceiling is a client-side choice

Arm C2 was accepted at 4350 bytes — larger than the client's own
`_METADATA_CEILING_BYTES = 4096` — and echoed back byte-exact. The client had
no keys it was permitted to shed, so it sent an over-ceiling payload, and the
server took it.

The ceiling is therefore client-side conservatism rather than a limit the API
imposes.

The server's actual limit is **not** established by this run. 4350 bytes is a
lower bound on what it accepts and nothing more. It was deliberately not probed
further: locating the true limit is work for whoever proposes changing the
constant, and an unprobed bound recorded honestly is more useful than a guess.

## What this does not establish

1. **Nothing about pricing.** Cost is $0 on this pre-prod tenant by decision.
   Envelope acceptance was verified; cost derivation was not. BACK-2676 remains
   the prerequisite for a real production tenant.
2. **One environment.** A single host, a single pre-prod tenant, and CLI 1.5.0
   only. The operator workstation runs 1.4.0; read-verb availability has
   differed across CLI versions in this project before.
3. **No server byte limit.** See above.
4. **Acceptance is not persistence forever.** Each arm was read back once,
   within roughly a minute of the write.

## Environment

- Host: the multiplex test VM, a clean box with no shared tenant. Chosen over
  the shared sandbox, where probe rows would land in another party's data, and
  over the live diagnosis host, which serves real traffic.
- CLI: `revenium` 1.5.0, installed from `revenium/tap/revenium` via linuxbrew
  to `/home/linuxbrew/.linuxbrew/bin/revenium`.
- Tenant: the pre-prod API, team `XPoqxyw`. No credential value appears in this
  document.

**The instrument was verified before it was trusted.** The host was carrying a
test double at `~/.local/bin/revenium` — a script that exits 0 for the calls
`hermes-report.sh` makes and performs no network I/O. Pointed at a live probe
it would have returned success for every arm while contacting nothing.

It was renamed rather than deleted, since it is the harness that verified an
earlier phase. Renaming was necessary but not sufficient: `ensure_path` places
`$HOME/.local/bin` ahead of brew prefixes, so a brew install alone would not
have won the PATH race. The check that `command -v revenium` resolves outside
`$HOME/.local/bin` was therefore run with `$HOME/.local/bin` placed first on
PATH deliberately, as the worst case. It resolved to the brew prefix.

The double advertised exactly two job subcommands; the real CLI advertises
twelve, including `outcome-history`. That difference is the direct evidence
that the arms above were not answered by the stub.

## Jobs created

Six throwaway jobs on the pre-prod tenant: one read-back gate
(`p49-gate-20260829-151406`) and five arms (`p49-armA`, `p49-armB`, `p49-armC1`,
`p49-armC2`, all suffixed `-20260829-152122`, and `p49-armC1b-20260829-152217`).

They are left in place as the evidence behind this record. `revenium jobs
delete` exists should they need removing.
