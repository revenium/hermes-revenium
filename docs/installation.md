# Installation

## GitHub tap workflow

After publishing this repository to GitHub:

```bash
hermes skills tap add <github-owner>/hermes-revenium-skill
hermes skills search revenium --source github
hermes skills install <github-owner>/hermes-revenium-skill/skills/revenium
```

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
    - /Users/johndemic/Development/projects/revenium/hermes-revenium-skill/skills
```

Hermes treats external skill directories as read-only discovery sources. The local `~/.hermes/skills/` directory still wins if the same skill name exists in both places.

## Local copy workflow

If you want the skill installed immediately without tap setup:

```bash
mkdir -p ~/.hermes/skills
cp -R skills/revenium ~/.hermes/skills/
bash ~/.hermes/skills/revenium/scripts/install-cron.sh
```

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
