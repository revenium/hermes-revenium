# revenium-install — troubleshooting decision tree

This decision tree routes each symptom to its most likely cause and exact
remediation. All commands are POSIX shell commands that invoke the skill's own
scripts. Paths assume the default install at `~/.hermes/skills/revenium/`; for a
fleet profile, prefix commands with that profile's `HERMES_HOME` /
`REVENIUM_STATE_DIR`.

Work from top to bottom. Earlier entries are more common and cheaper to check.

---

## `hermes skills install` "succeeded" but `scripts/install.sh` is missing

Cause: `hermes skills install` ships `SKILL.md` plus only the support files
`SKILL.md` names as bundle-relative paths, from an allowlist of directories that
excludes `plugins/` entirely. It never ships `scripts/` or `plugins/`.

Fix: run the bootstrap. It clones the repo, adds the missing directories, and
hands off to the installer):

```sh
bash ~/.hermes/skills/revenium/references/bootstrap.sh
# or, if bootstrap.sh didn't come down either:
git clone --depth 1 https://github.com/revenium/hermes-revenium.git /tmp/hermes-revenium \
  && bash /tmp/hermes-revenium/install.sh
```

---

## `hermes skills install` refuses with a `CAUTION` / scanner verdict

As of 2026-08-21, the skill scans `SAFE` and installs with no flags; see "What
the security scanner reports" in the README. A refusal is not expected. The scan
reports `MEDIUM` findings for cron `persistence` and a documented `git clone`
under `supply_chain`; those findings do not block an install on their own.

Cause: Hermes produces the scanner verdict, so the
verdict can change independently. A `CAUTION` verdict means the scan graded
findings more severely than the version observed above.

Fix: confirm that the findings are expected before bypassing the
scanner. Treat `--force` as a considered decision, not a reflex:

```sh
hermes skills install revenium/hermes-revenium/skills/revenium --force
```

Also [open an issue](https://github.com/revenium/hermes-revenium/issues) with the
verdict and findings. A change from `SAFE` is worth knowing about.

---

## Every `guardrails` / `jobs create` fails with `teamId is required` (HTTP 400)

Cause: only the API key is configured. Completions meter, but jobs and
guardrails need all **four** credentials (API Key, Team ID, Tenant ID, Owner ID).

Check and fix:

```sh
revenium config show     # confirm all four are non-empty
# re-run the installer; it walks every field (api-url included), showing the
# current value as the default — Enter keeps it, typing replaces it:
bash ~/.hermes/skills/revenium/scripts/install.sh
```

---

## Jobs appear in Revenium but `jobs transactions <id>` shows "No transactions found"

Cause (BUG-1 class): the classifier writes the `.ready` sentinel only after
its slow job-inference LLM call finishes. If the reporter's age-fallback fires
before that (window shorter than job-inference latency), it meters + ledgers the
completions before the job marker exists and per-muid dedup permanently orphans
them.

Fix: ensure the settle window exceeds worst-case job-inference latency
(observed ~200s under load). The shipped default is **600s**. Do not lower it on
installs that run the classifier plugin. Check what's baked into cron:

```sh
crontab -l | grep -o 'REVENIUM_CRON_SETTLE_SECONDS=[0-9]*'
```

If it's small (e.g. 45), re-install the cron so the current default is baked in:

```sh
bash ~/.hermes/skills/revenium/scripts/install-cron.sh --force          # single host
bash ~/.hermes/skills/revenium/scripts/install-cron.sh --all-profiles   # fleet
```

Metering-only installs (no classifier plugin, no job markers) can safely set a
small value via `REVENIUM_CRON_SETTLE_SECONDS` in the profile's env — there is no
job inference to wait for.

---

## Hooks are registered but nothing gets captured (tool-events stay empty)

Cause: hooks are inert until consented. A headless or gateway-served
profile never shows the interactive approval prompt. Set `hooks_auto_accept` or
`pre_llm_call`, `pre_tool_call`, and `post_tool_call` will never fire.

Diagnose:

```sh
bash ~/.hermes/skills/revenium/scripts/hooks-status.sh; echo "exit=$?"
# exit 1 = not registered; exit 2 = registered but idle (likely not approved / not auto-accepted)
```

Fix (gateway-served / fleet):

```sh
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh --auto-accept                 # single host
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh --all-profiles --auto-accept  # fleet
```

Shadow / metering-only mode: install only the tool-event hook (the two `pre_*`
enforcement hooks are inert overhead):

```sh
bash ~/.hermes/skills/revenium/scripts/install-hooks.sh --metering-only --auto-accept
```

---

## Only one profile is being metered on a fleet host

Cause (BUG-3 class): an older `install-cron.sh` keyed every profile on one
fixed crontab marker, so each per-profile install overwrote the previous.

Check: there should be one distinct marker per metered profile:

```sh
crontab -l | grep -o '# hermes-revenium-metering[-A-Za-z0-9]*' | sort -u
```

Fix: re-install the fleet. Each profile now gets a unique
`# hermes-revenium-metering-<profile>` marker and its own baked env:

```sh
bash ~/.hermes/skills/revenium/scripts/install.sh --all-profiles
```

---

## Cron spams "No such file or directory" every minute

Cause (BUG-7 class): `~/.hermes` was wiped or reset, but the metering crontab line
survived, pointing at a now-missing `cron.sh` (or `cron-fleet.sh`).

Fix: `install-cron.sh` auto-reconciles orphaned metering lines on its next
run; or remove them outright:

```sh
bash ~/.hermes/skills/revenium/scripts/install-cron.sh --all-profiles   # reconciles orphans, re-wires live profiles
# or, to remove every metering line (per-profile markers + fleet wrapper):
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
```

`uninstall-cron.sh` preserves unrelated (foreign) crontab lines.

---

## Multiplex mode: a profile's markers/sentinels land in the wrong home

Cause (BUG-4 class): in `gateway.multiplex_profiles: true`, one gateway serves
every profile and sessions are namespaced `agent:<profile>:…`. A classifier that
resolved paths only from the process `HERMES_HOME` would write every profile's
markers into the default home, so the per-profile cron never sees them.

Expected behavior: the classifier resolves the owning profile's
home/state.db/markers/`.ready` **per session** from the namespace. Verify markers
are landing under the owning profile:

```sh
ls -1 ~/.hermes/profiles/gtm/state/revenium/markers/ | head       # profile's own markers
ls -1 ~/.hermes/state/revenium/markers/ | head                    # default home (should NOT hold agent:gtm:* files)
```

If markers for a namespaced session are in the default home, the plugin is stale
Re-install it and restart the gateway:

```sh
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
```

---

## Spend shows up entirely as `--task-type unclassified`

Causes and checks:

- Classifier plugin not installed or gateway not restarted: the plugin writes
  the task markers. Re-run and restart:
  ```sh
  bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
  ```
- Hooks inert (self-classification never happens): see "Hooks are registered
  but nothing gets captured" above.
- Reporter falling through to the zero-marker path: inspect the cron log for
  `marker-read fall-through` warnings:
  ```sh
  grep -E 'fall-through|unclassified' ~/.hermes/state/revenium/revenium-metering.log | tail
  ```

---

## Spend lands in the wrong / unexpected ORGANIZATION

Cause: `organizationName` in `config.json` is the `ORGANIZATION` dimension
(a company/product). Setting it to an agent or profile name pollutes that
dimension. Per-agent attribution is the `AGENT` dimension
(`REVENIUM_AGENT_NAME` / `--agent`), which fleets default to `Hermes-<profile>`.

Check and fix:

```sh
python3 -c "import json;print(json.load(open('$HOME/.hermes/state/revenium/config.json')).get('organizationName'))"
# set a real org (persisted even with --skip-guardrails):
bash ~/.hermes/skills/revenium/scripts/install.sh --organization-name <company-or-product>
```

The cron also logs a `WARN` when `organizationName` looks like an agent name.

---

## Nothing is being metered at all

Walk the pipeline in order:

```sh
command -v revenium sqlite3 python3     # tools present?
revenium config show                    # all four creds?
crontab -l | grep hermes-revenium-metering   # cron installed?
ls ~/.hermes/state.db                   # Hermes session DB exists?
tail -n 40 ~/.hermes/state/revenium/revenium-metering.log   # what does the reporter say?
```

The reporter fails open (logs a `warn` and exits 0) when a tool or the DB is
missing, so the log is the source of truth for why a tick did nothing.
