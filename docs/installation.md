# Installation

## GitHub tap workflow

```bash
hermes skills tap add revenium/hermes-revenium
hermes skills install revenium/hermes-revenium/skills/revenium --force
```

The `--force` flag is required because Hermes' security scanner correctly flags the skill's crontab installer as a persistence mechanism. See the "About the `--force` flag" callout in the [README](../README.md) for details.

Hermes discovers custom taps by scanning the repo's `skills/` directory. This repository intentionally places the skill at:

```text
skills/revenium/
```

so the default tap path works with `hermes skills tap add owner/repo`.

## Local development workflow

For local iteration, point Hermes at the repo directly:

```yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-revenium/skills
```

Hermes treats external skill directories as read-only discovery sources. The local `~/.hermes/skills/` directory still wins if the same skill name exists in both places.

## Local copy workflow

If you want the skill installed immediately without tap setup:

```bash
mkdir -p ~/.hermes/skills
cp -R skills/revenium ~/.hermes/skills/
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

## Classifier plugin install (required for job tracking)

**None of the three install methods above install the bundled `revenium-classifier`
plugin** — `hermes skills install`, `external_dirs`, and a plain `cp -R` of the skill
all place content under `~/.hermes/skills/`, but Hermes loads `on_session_end` plugins
from a separate root: `~/.hermes/plugins/<name>/`. Without this step the classifier
never runs and no `kind:"job"` markers are written, so job usage never reaches Revenium.

The simplest correct install is the local-setup helper, which installs the skill **and**
the plugin, enables the plugin in `config.yaml`, removes stray shadowing copies, and
seeds the taxonomies:

```bash
bash install.sh
hermes gateway restart   # restart so the agent loads the updated plugin
```

If you installed the skill by the GitHub tap, `hermes skills install`, or `external_dirs`,
run the bundled installer:

```bash
bash ~/.hermes/skills/revenium/scripts/install-plugin.sh
```

This copies the plugin into `~/.hermes/plugins/`, adds it to `plugins.enabled` in
`~/.hermes/config.yaml`, and runs `hermes gateway restart` so the change takes effect.
Idempotent — re-run safely. Pass `--dry-run` to preview, `--no-restart` to skip the
gateway restart (useful in CI / containers where the gateway isn't running).

Re-run this step on **every upgrade** — updating only `~/.hermes/skills/` leaves the
active plugin stale. Never leave backup copies of the skill (e.g. `revenium.bak.*`)
inside `~/.hermes/skills/`: plugin discovery scans their bundled `plugins/` dirs and a
stale duplicate can shadow the real one.

## Revenium CLI setup

The skill expects `revenium config show` to succeed. If it does not, configure the CLI first:

```bash
revenium config set key <api-key>
revenium config set team-id <team-id>
revenium config set tenant-id <tenant-id>
revenium config set user-id <user-id>
```

## Hermes runtime expectations

The skill stores runtime state in:

```text
~/.hermes/state/revenium/
```

This keeps mutable state out of the skill directory itself and matches Hermes-style separation between:

- `~/.hermes/skills/` → skill content
- `~/.hermes/state/` → runtime state and logs

## Operational hygiene

Over time, the skill accumulates JSONL marker files under `~/.hermes/state/revenium/markers/` — one per Hermes session. These files are the input to the cron's per-turn attribution split (see `references/setup.md` for the full attribution and marker/taxonomy contract). On long-running hosts they grow without bound unless periodically pruned.

The skill ships an operator-invoked pruning script for this purpose:

```bash
# Preview what would be removed (no files deleted)
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run

# Remove stale marker files
bash ~/.hermes/skills/revenium/scripts/prune-markers.sh
```

The script determines staleness by reading the latest ledger row for each session. Marker files whose most-recently-reported ledger timestamp is older than the retention threshold are removed. Orphan markers (no ledger entry) fall back to file modification time for the staleness check.

- **Default retention:** 30 days.
- **Override:** set `REVENIUM_MARKER_RETENTION_DAYS=<n>` in the environment before invoking the script to use a different threshold.
- **Marker location:** `~/.hermes/state/revenium/markers/`

The script is NOT wired into the per-minute cron — it is an operator-invoked maintenance action. Run it periodically (for example, monthly) to reclaim disk space. For the full operator runbook including the manual UAT triple-case (old / fresh / orphan fixture), see [`references/setup.md`](../skills/revenium/references/setup.md).
