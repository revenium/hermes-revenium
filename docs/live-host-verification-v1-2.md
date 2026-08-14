# Live-Host Verification - CLI v1.3.0 Compatibility & Multi-Agent Attribution

## Release gate

**Any change to the metering reporter, the guardrail checker, the shared
helper library, the tool-event reporter, or the classifier package MUST
re-pass this live-host verification before it ships.** These five files are
the only place in this skill that can silently double-bill a tenant or
misattribute spend to the wrong agent or squad, and no unit test can prove
their guards hold against a real multi-profile fleet — real concurrent
gateways, a real out-of-tree cron wrapper repointing `HERMES_HOME` per
profile, and a real platform on the other end deduplicating by transaction
id. This document mirrors the headline findings and the replayable procedure
from a real verification pass so the proof survives loss of the (gitignored)
planning directory that originally captured it.

There is no retry budget on the idempotency check specifically: a forced
re-run that grows any ledger's line count, or that a duplicate-prefix scan
flags, blocks the release until the cause is understood. Everything else in
this document (pagination, stderr isolation, trace-type, squad flags, agent
naming, squad grouping) fails loudly if it regresses; ledger idempotency is
the one guarantee whose violation costs real money silently.

## When to run

Run this verification before any release that modifies:

- `skills/revenium/scripts/hermes-report.sh` — the reporter: ledger
  idempotency, squad flags, trace-type, agent naming
- `skills/revenium/scripts/guardrail-check.sh` — the guardrail checker:
  pagination request bound, stderr isolation
- `skills/revenium/scripts/common.sh` — the shared helper library: ledger and
  state path declarations, capability probes
- `skills/revenium/scripts/tool-event-report.sh` — the tool-event reporter:
  shares the ledger idempotency idiom with the main reporter
- `skills/revenium/plugins/revenium-classifier/` — the classifier package:
  trace-type population, hook registration, the once-per-session inference
  bound

**The load-bearing question is: does a forced, confirmed-executed re-run of
the reporting pipeline against an already-reported ledger produce zero new
ledger lines and zero new metering calls, on every ledger surface?**

## What was verified, and how

| Behavior | Method | Result |
|---|---|---|
| Pagination request count | Replayed-argv `--verbose` wire trace, corroborated by a real tick's log timestamps and the repository's own exact-equality unit test | PASS, qualified — 2 requests on a steady-state tick, exact equality with the declared bound; the count is proven for the reconstructed argv shape, not for the production call path itself. See Known limitations |
| stderr isolation | Induced multi-page response via verb substitution onto a real, high-volume list command | PASS — the pagination note lands on stderr only; stdout stays clean, parseable JSON |
| Trace-type population | Induced multi-agent session; real LLM-inferred labels read from the classifier's marker files | PASS — non-fallback labels observed on both the root and the subagent session |
| Squad flags | Same induced session; emission-side argv plus a platform read | PASS — squad id equals the root session id on both rows; the role split lands as `root` on the root's rows and `subagent` on the subagent's rows, confirmed on the platform side per row, not only at emission |
| Agent naming | Same induced session; platform read | PASS — squad name matches the profile's configured agent name on both rows |
| Ledger idempotency | Forced re-run: three confirmed-executed pipeline invocations, strictly sequential, against a frozen snapshot; byte-for-byte hash comparison across all three ledger surfaces | PASS, qualified — zero new lines and zero new metering calls across three verified-executed iterations on one profile; see Known limitations for scope |
| Squad grouping | Platform read: the squad-detail and timeline commands called directly with the raw root session id, plus a fragmentation test against the subagent's own id | PASS — correct membership, no fragmentation (the subagent's own id returns not-found); the timeline reports `role` per event and it resolves `root` on the root's rows and `subagent` on the subagent's rows |

## Procedure

The four stages below are the replayable part of this document. Placeholders
(`<host>`, `<ssh-key>`, `<profile>`, `<team-id>`, `<tenant-id>`) stand in for
real values that live only in the local, gitignored evidence artifact.

### 1. Deploy swap sequence

```bash
ssh -i <ssh-key> <user>@<host>

# Pause the fleet cron so no tick can contend with the swap.
crontab -l > /tmp/crontab.pre-deploy.bak
crontab -e   # comment out the metering line

# Drain any in-flight wrapper passes before touching files under it.
pgrep -af 'cron-fleet|hermes-report|tool-event-report'
# wait until this returns nothing

# Back up the deployed skill tree — this is the rollback path; never delete it.
cp -a ~/.hermes/skills/revenium ~/.hermes/skills/revenium.pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)

# Dry-run the sync first. A host-only wrapper script (invoked by the fleet's
# crontab, not tracked in this repository) can live inside the target
# directory — do not let a plain --delete sync remove it. Read the dry run's
# itemized output before running the real sync.
rsync -avn --delete --itemize-changes skills/revenium/ <host>:~/.hermes/skills/revenium/

# Run the corrected sync, excluding anything the dry run flagged as host-only,
# plus build artifacts that should never leave the working tree.
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '<host-only-wrapper>.sh' \
  skills/revenium/ <host>:~/.hermes/skills/revenium/

# Spot-check: syntax-check every shell script, byte-compile every Python
# file, and re-resolve the capability probes against the swapped-in tree.
bash -n skills/revenium/scripts/*.sh
python3 -m py_compile skills/revenium/plugins/revenium-classifier/*.py

# Resume the cron and confirm exactly one metering line is registered.
crontab -e   # uncomment the metering line
crontab -l | grep -c 'cron-fleet\|hermes-revenium-metering'   # expect 1
```

### 2. Per-profile classifier rollout

```bash
# Compare each profile's installed classifier hash against the shared skill
# tree's source hash. Directory presence is not proof of currency — only a
# content-hash comparison is.
sha256sum ~/.hermes/skills/revenium/plugins/revenium-classifier/classifier.py
for p in <profile-list>; do
  sha256sum "~/.hermes/profiles/${p}/plugins/revenium-classifier/classifier.py"
done

# Confirm no active sessions before restarting a profile's gateway.
# Then, per profile, lowest-traffic first:
HERMES_HOME="~/.hermes/profiles/<profile>" bash scripts/install-plugin.sh --no-restart
systemctl --user restart "hermes-gateway-<profile>.service"

# Re-verify: hash matches source, plugins.enabled lists the classifier,
# gateway unit is active.
bash scripts/plugin-status.sh
```

### 3. Forced re-run discipline

This is the step the milestone's idempotency proof depends on, and the one
place a false pass is easy and invisible: the reporter's entry point holds an
exclusive non-blocking lock for its whole run, so a second invocation started
before the first finishes exits zero having touched nothing. Never background
or parallelize these iterations.

```bash
# 1. Freeze a snapshot before touching anything.
for f in revenium-hermes.ledger revenium-jobs.ledger revenium-tool-events.ledger; do
  sha256sum "~/.hermes/profiles/<profile>/state/revenium/${f}"
  wc -l      "~/.hermes/profiles/<profile>/state/revenium/${f}"
done

# 2. Run the pipeline to full completion, three times, strictly sequential.
#    Never use '&', never background, never run two profiles' iterations
#    concurrently.
HERMES_HOME="~/.hermes/profiles/<profile>" \
REVENIUM_STATE_DIR="~/.hermes/profiles/<profile>/state/revenium" \
REVENIUM_AGENT_NAME="Hermes-<profile>" \
REVENIUM_CRON_SETTLE_SECONDS=600 \
  bash skills/revenium/scripts/cron.sh
# repeat this exact invocation two more times, waiting for each to exit
# before starting the next

# 3. After EACH iteration, before starting the next: confirm that
#    iteration's own log tail does NOT contain the lock-contention line.
#    If it does, that iteration proved nothing — discard it and re-run.
tail -n 50 "~/.hermes/profiles/<profile>/state/revenium/revenium-metering.log" \
  | grep -c 'prior tick still active, skipping this minute'   # must be 0

# 4. Re-hash and re-diff against the step-1 snapshot. A changed hash is not
#    automatically a failure — diff the file and confirm every added line is
#    a genuinely new session-and-token pair, never a repeat of one already
#    present.
```

### 4. The four watch-signal checks

```bash
# Signal 1 — duplicates: compare the distinct session-and-token prefix count
# against the total line count on every ledger file. Equal counts mean no
# duplicates.
awk -F: '{print $1":"$2":"$3}' revenium-hermes.ledger | sort -u | wc -l
wc -l revenium-hermes.ledger

# Signal 2 — log errors: count WARN and ERROR lines now, subtract the
# pre-deploy baseline. A positive delta must be individually accounted for,
# not waved through.
grep -c '\[WARN \]\|\[ERROR\]' revenium-metering.log

# Signal 3 — classifier inference count: confirm one marker pair per session,
# not one per turn.
grep -c '"task_type"' markers/*.jsonl

# Signal 4 — platform-side row count: independently of the local ledger,
# count metered rows on the platform for one known session, before and after
# the forced re-run. This is the check that catches a duplicate landing
# server-side even when the local ledger looks clean.
revenium squads get <root-session-id> --output json
```

## Known limitations

**Induced, not organically observed:**

- The multi-agent dispatch tree used to prove squad grouping was a
  deliberately sent prompt, chosen to force exactly one subagent dispatch —
  not naturally occurring traffic. The prediction was written down before the
  prompt was sent, specifically so the result would be falsifiable rather
  than reconstructed after the fact.
- The pagination stderr note was induced by substituting a different,
  naturally high-volume list command for the one this skill's hot path
  actually calls, because the verifying tenant's real data on that hot-path
  command could not reach a second page at any page size.

**Measured on a replay, not on the production call path:**

- The per-tick request count was obtained by reconstructing the guardrail
  stage's two request-issuing invocations from the deployed script and
  replaying them with the CLI's verbose flag. That proves how many requests
  *that argv shape* puts on the wire — it does not prove that the unmodified
  production script issues that argv on a real tick. This phase was barred
  from editing the scripts under test, so the production call path was never
  instrumented directly. The result rests on three legs together: this
  replay, a real tick's log timestamps establishing the unmodified script ran
  in that window, and the repository's own exact-equality request-bound unit
  test. Read the request count as strong converging evidence, not as a direct
  measurement of production.
- The classifier rollout to nine of ten profiles was an operator-authorized
  production change performed as part of this verification, not a passively
  observed pre-existing state.
- The forced re-run itself is, by design, extra pipeline invocations outside
  the normal per-minute schedule — deliberately run to defeat the risk that a
  passive observation window might simply never contain a re-run collision.

**Left unanswered:**

- The platform-side row count was not independently re-checked in a bracket
  specifically before and after the forced re-run; the nearest available
  platform read predates it.
- The forced re-run's ledger comparisons were exercised on one profile, not
  the full fleet.
- A jobs-ledger creation-guard-versus-outcome-guard split comparison was not
  performed separately from the aggregate file-level check.
- A same-timestamp search across every profile's session ledger (two lines
  for one session sharing a timestamp) was not performed fleet-wide.
- A fleet-wide post-re-run WARN-count delta was not independently re-tallied;
  a known, already-diagnosed, pre-existing re-warn condition (unrelated to
  this release) accounts for ongoing WARN growth and is tracked separately.
- A live before/after file-level snapshot of the guardrail-status file on a
  real tick (as opposed to the structural stdout/stderr argument) remains
  open.
*(A limitation previously listed here — that per-row confirmation of the
subagent role was not observable — was withdrawn after re-checking. The
squad-detail command's agent array does aggregate by agent and shows only one
role, but the timeline command reports `role` on every individual event, and it
resolves correctly per row. See the Squad flags and Squad grouping rows above.)*

## Verified against

- CLI version: `revenium 1.3.0`
- Date: 2026-08-14
- Host: a production fleet host running ten metered Hermes profiles behind a
  host-only, out-of-tree cron wrapper. Full raw captures (command output,
  hashes, session ids, and per-profile identifiers) live only in this
  repository's local, gitignored planning evidence artifact — this document
  is the scrubbed, committed mirror of its headline findings.
