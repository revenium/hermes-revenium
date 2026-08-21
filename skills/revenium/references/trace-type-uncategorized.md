# Trace type shows `uncategorized`

**Symptom.** Metered completions in Revenium carry `traceType: uncategorized` instead of the
classified job type (e.g. `code_review`, `refactor`, `planning`) — for one session or across an
entire fleet. The cron log is otherwise healthy: `revenium-metering.log` is full of successful
`Reported: session=...` lines and the ledger (`revenium-hermes.ledger`) keeps growing. Metering
itself is working; the job label just never made it onto the wire.

**The one-line narrowing.** `--trace-type` is only ever sent when the installed `revenium` CLI
advertises the flag — a CLI that lacks it gets no `--trace-type` argument at all, not a literal
`uncategorized` one. So if you are actually seeing the string `uncategorized` in Revenium (not
just a missing field), that already proves the CLI is capable and the reporter got as far as
looking up a job classification for the session and found nothing usable. Don't spend time
checking `revenium --version` or CLI flags for this symptom — start at the marker lookup instead.

**The resolution chain.** Two independent processes have to agree on one thing. The
`revenium-classifier` Hermes plugin writes a `kind:"job"` record into the session's marker file,
under the profile that owns the session. The cron reporter (run every minute) reads that record
back from the markers directory its own environment resolves to, for the *root* session of the
trace — a subagent's completions inherit the root session's job type, so every completion sharing
a trace ships the identical `traceType`; a wrong or missing value at the root propagates to
everything under it.

```bash
# Where the reporter (cron-side) resolves the markers directory for the default profile
echo "${REVENIUM_MARKERS_DIR:-${HOME}/.hermes/state/revenium/markers}"

# The marker file a specific root session's job record would live in
cat ~/.hermes/state/revenium/markers/<root-session-id>.jsonl 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "no marker file for this session"
```

If that marker file does not exist, or exists with no `kind:"job"` line inside it, the reporter
falls back to `uncategorized` for every completion in that trace. The sections below walk the
on-disk signatures for why.

## No marker file for the root session

**Symptom.** No file exists at all under the resolved markers directory for the trace's root
session id.

```bash
ls -la ~/.hermes/state/revenium/markers/<root-session-id>.jsonl
# ls: cannot access '...': No such file or directory
```

**Root cause.** The classifier's `on_session_end` hook either never ran for this session, or ran
and failed before reaching the marker write. A registration outage — the plugin never loaded by
Hermes at all — is the specific failure that produced a live nine-day fleet-wide incident, and it
is the one the check below is built to catch.

**Fix.** First confirm which process actually serves this profile — the plugin is loaded once
at process start, and on a desktop-app host the gateway is usually not the owner:

```bash
ps -axo pid,lstart,command | grep -E 'hermes.*(serve|gateway run)' | grep -v grep
```

A `--profile <name> serve` process is spawned by the Hermes desktop app: quit and reopen the
app to reload it. `hermes gateway restart` will not affect it, and a gateway whose
`HERMES_HOME` is the default home never touches a profile at all. Compare each process's start
time against the plugin's mtime — a server older than the plugin cannot have loaded it.

Then run the registration-level health check this skill ships, from the installed scripts
directory:

```bash
bash ~/.hermes/skills/revenium/scripts/plugin-status.sh
```

This replaces an older instruction that listed the skill bundle's own plugin source directory.
That directory is not one of Hermes' plugin-discovery roots, so a listing of it succeeds whether
or not the plugin is actually loaded — it reported "present" throughout the entire nine-day
outage. `plugin-status.sh` checks registration and runtime liveness instead, and its exit code
tells you what to do next:

| Exit code | Meaning | Next step |
|-----------|---------|-----------|
| `1` | Not registered — the plugin directory is absent from a Hermes plugin-discovery root, or it is not listed in `plugins.enabled` | Run `bash ~/.hermes/skills/revenium/scripts/install-plugin.sh` |
| `2` | Registered but not firing (liveness `stalled`) — the plugin is placed and enabled, but the running gateway is not producing sentinels for recently-ended sessions | Restart the Hermes gateway so it reloads the plugin, then re-run `plugin-status.sh` to confirm |
| `0` | Healthy — the registration path is fine | The cause is elsewhere in this document; continue to the sections below |

If `plugin-status.sh` reports exit `0` and the marker file is still never written after a fresh
session completes, this is not something an operator can resolve by re-running the cron — it
needs the classifier plugin itself investigated. Re-running
`bash ~/.hermes/skills/revenium/scripts/cron.sh` will not create the marker; the marker is written
by the classifier, not the reporter.

## Marker file present, no job record

**Symptom.** The marker file exists but contains no line with `"kind": "job"`.

```bash
cat ~/.hermes/state/revenium/markers/<root-session-id>.jsonl | grep '"kind":"job"'
# (no output)
```

**Root cause.** The classifier attempted classification but produced nothing usable: the LLM
call returned zero jobs (a valid, non-error outcome), the LLM call itself failed, or every
candidate job it proposed failed label validation. These three cases currently leave an
identical on-disk footprint — see the note at the end of this file for what that means for
diagnosing this specific mode today.

**Fix.** There is nothing to clear or reset here — a marker file with task records but no job
record reflects the classifier's own judgment about that session's transcript. If this happens
for every session on a profile, treat it the same as the no-marker-file case above and escalate
to the classifier plugin itself.

## Markers directory mismatch (multi-profile / multiplexed installs)

**Symptom.** The classifier writes the marker to one directory; the reporter reads from a
different one. The marker file exists on disk, but not where the reporter is looking.

```bash
# What HERMES_HOME the cron actually uses for this profile (check the crontab entry)
crontab -l | grep -i hermes-revenium

# The profile-specific markers directory the classifier resolves to for a
# namespaced session id (agent:<profile>:...)
ls -la ~/.hermes/profiles/<profile>/state/revenium/markers/

# The directory the reporter's environment resolves to for the same run
echo "${REVENIUM_MARKERS_DIR:-${REVENIUM_STATE_DIR:-${HOME}/.hermes/state/revenium}/markers}"
```

**Root cause.** In a multi-profile fleet, each profile has its own `~/.hermes/profiles/<name>/`
home. If the cron wrapper that invokes `cron.sh` sets a different `HERMES_HOME` /
`REVENIUM_STATE_DIR` per profile than the one the classifier's own Hermes process resolves for
that profile, the two sides read and write different `markers/` directories for the same
session, and the reporter never sees a marker that genuinely exists.

**Fix.** Confirm both sides resolve to the identical directory for the profile in question — the
cron wrapper's `HERMES_HOME`/`REVENIUM_STATE_DIR` assignment for that profile must match what the
classifier plugin sees inside that profile's own gateway process. If your install runs Hermes'
`gateway.multiplex_profiles` mode (a single gateway process serving multiple profiles via
namespaced session ids), also confirm that setting is consistent across the fleet — this mode
changes which resolution mechanism is live and is the one this failure mode is most likely to
affect.

### A recorded deployment assumption, not a supported configuration

Some fleets are driven by a wrapper script that is not part of this repository — for example, a
`cron-fleet.sh` that this skill does not ship and cannot read. This is a recorded assumption about
one such deployment, nothing more: no code in this repository accommodates a file it cannot read,
and there is no detection step or compatibility shim for it here.

Such a wrapper typically repoints `HERMES_HOME` to give each profile its own Hermes home, rather
than relying on the classifier's namespaced-session multiplex mechanism described above. In that
layout the cron side and the classifier side agree on the markers directory by construction —
both run against the exact same per-profile `HERMES_HOME`, so there is no separate namespace for
the two to disagree about.

Do not run this repository's own repository-native per-profile cron (`install-cron.sh` invoked
once per profile home) alongside such a wrapper. Two schedulers metering the same sessions
double-report: each scheduler maintains its own ledger view of what it has already reported, so
running both against the same profile's sessions produces duplicate `revenium meter completion`
calls for the same usage. Pick exactly one fleet-scheduling mode per profile and never mix them.

## Reporter runs before the classifier writes the marker

**Symptom.** The marker eventually appears, but the completion had already been reported as
`uncategorized` on an earlier cron tick.

```bash
# Compare the ledger row's timestamp (field 4) against the marker's own job-record timestamp
grep "^HERMES:<root-session-id>:" ~/.hermes/state/revenium/revenium-hermes.ledger
# HERMES:<sid>:<total_tokens>:<now_ts>:<muid_or_synthetic>
```

The ledger line is **5 colon-delimited fields**, not 4: `HERMES:<session_id>:<total_tokens>:
<timestamp>:<muid>`. The timestamp is **field 4** (a millisecond-precision float, e.g.
`1785250329.656`), not the last field — the 5th field is a per-completion marker id (or, on the
zero-marker fallback path, a synthetic `unclassified-<timestamp>` value with no dots). If you are
comparing this timestamp against something else to check a timing race, use field 4.

**Root cause.** The reporter defers a session until either the classifier's `.ready` sentinel
lands under the markers directory's `.ready/` subdirectory, or the session ages past a settle
window — whichever comes first. If job inference is slow enough (heavy concurrent load, a slow
LLM call) that neither the sentinel nor the marker lands before the settle window elapses, the
reporter reports the session as `uncategorized` and never revisits it, even after the marker
eventually shows up.

**Fix.** Check the settle window actually in force on your host — do not assume the default:

```bash
crontab -l | grep -o 'REVENIUM_CRON_SETTLE_SECONDS=[0-9]*'
# no output means no override — the in-repo default of 600 seconds applies
```

If job-inference latency on your fleet regularly exceeds the settle window, that is a capacity /
timing tuning problem (raise `REVENIUM_CRON_SETTLE_SECONDS`), not a code bug — but confirm via
the timestamp comparison above that this is actually what happened before changing the setting,
since it produces the same end symptom as the other three failure modes.

## Reason codes in the metering log

Every time the reporter falls back to `uncategorized`, it also writes exactly one `reason=` line
to `revenium-metering.log` naming which of a closed, three-literal vocabulary caused it. Grep the
log directly rather than guessing from the wire value alone:

```bash
grep 'reason=' ~/.hermes/state/revenium/revenium-metering.log | tail -20
```

| Reason literal | On-disk symptom | Next step |
|-----------------|------------------|-----------|
| `reason=plugin_unregistered` | `plugin-status.sh` reports the classifier is not registered (exit `1`) or registered but not firing (exit `2`) — checked and reported FIRST, ahead of any marker-state reasoning | See "No marker file for the root session" above; run `plugin-status.sh` and follow its exit-code table |
| `reason=no_job_classified` | The plugin is registered and healthy, but the marker lookup found nothing usable — either no marker file yet, or a marker file with no `kind:"job"` line | See "Marker file present, no job record" and "Reporter runs before the classifier writes the marker" above |
| `reason=marker_lookup_failed` | The plugin is registered and healthy, but reading the marker file itself raised an error (for example, something other than a plain file occupying that path, or a permissions problem) | Inspect the marker path directly with `ls -la` and check ownership/permissions; this is not the same symptom as an absent file |

`reason=plugin_unregistered` is the one literal no in-plugin diagnostic could ever have reported —
the failure mode it names is the plugin never loading in the first place, so nothing running
inside the plugin ever gets a chance to log anything. That is exactly why this check runs on the
cron side instead.

---

**A note on telling these apart.** As of this version of the skill, the metering log's `reason=`
line separates a registration outage (`plugin_unregistered`) from every other cause of
`uncategorized`, and separates a genuine marker-read error (`marker_lookup_failed`) from an
absent-or-jobless marker (`no_job_classified`). What it does not separate is the finer split
inside "marker present, no job record": whether the LLM call returned zero jobs, the LLM call
itself failed, or every candidate job failed label validation. Those three causes still share the
same `no_job_classified` reason code and the same on-disk marker shape — telling them apart still
means inspecting the classifier plugin's own logs, not this document.
