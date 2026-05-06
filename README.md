# Hermes Revenium Skill

Official Revenium skill repository for **Hermes Agent**.

This repo packages a Hermes-native `revenium` skill that adds:

- **budget enforcement** before costly operations
- **usage metering** from `~/.hermes/state.db` into Revenium
- **autonomous halt behavior** when spend crosses a configured threshold
- **Hermes-native alert delivery** for halt notifications

The repository is structured for Hermes skill sharing via custom GitHub taps.

## Repository layout

```text
hermes-revenium-skill/
├── skills/
│   └── revenium/
│       ├── SKILL.md
│       ├── references/
│       └── scripts/
├── docs/
├── examples/
└── tests/
```

## Install options

### Option 1: GitHub tap (recommended for shared distribution)

Once this repo is published:

```bash
hermes skills tap add <github-owner>/hermes-revenium-skill
hermes skills search revenium --source github
hermes skills install <github-owner>/hermes-revenium-skill/skills/revenium
```

### Option 2: Local development via external skill directory

Add the repo's `skills/` directory to your Hermes config:

```yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-revenium-skill/skills
```

Then restart Hermes or start a new session.

### Option 3: Copy the skill locally

```bash
mkdir -p ~/.hermes/skills
cp -R skills/revenium ~/.hermes/skills/
```

## Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com/docs/)
- [`revenium` CLI](https://docs.revenium.io/for-ai-agents)
- `sqlite3`
- `python3`

Verify:

```bash
revenium config show
sqlite3 --version
python3 --version
```

## First-time setup

1. Install the skill.
2. Install the metering cron:

   ```bash
   bash ~/.hermes/skills/revenium/scripts/install-cron.sh
   ```

3. Load the skill in Hermes and use `/revenium` or ask Hermes to configure Revenium budget enforcement.
4. Provide:
   - budget threshold
   - budget period
   - optional organization name
   - optional autonomous halt notification target

Skill state is stored under:

```text
~/.hermes/state/revenium/
```

including:

- `config.json`
- `budget-status.json`
- `revenium-hermes.ledger`
- `revenium-metering.log`

## Manual commands

```bash
# Run metering + budget check once
bash ~/.hermes/skills/revenium/scripts/cron.sh

# Run only the Hermes SQLite reporter
bash ~/.hermes/skills/revenium/scripts/hermes-report.sh

# Run only the budget check
bash ~/.hermes/skills/revenium/scripts/budget-check.sh

# Clear an active halt
bash ~/.hermes/skills/revenium/scripts/clear-halt.sh

# Remove cron entry
bash ~/.hermes/skills/revenium/scripts/uninstall-cron.sh
```

## Testing

This repo uses stdlib `unittest` smoke checks:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Notes

- This repo is **Hermes-only and clean** — no legacy runtime assumptions.
- The skill is packaged under `skills/revenium` so Hermes custom taps can discover it under the default `skills/` repo path.
- A future publish step can add a GitHub remote and optionally a well-known skills index.
