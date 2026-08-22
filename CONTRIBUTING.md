# Contributing

Thanks for taking the time. This is a [Revenium Labs](https://github.com/revenium/.github/blob/main/LABS.md)
project — field-developed and best-effort — so issues and PRs are genuinely welcome, and
we're happy to work with you to make it fit your environment.
[Come talk to us on Discord](https://discord.gg/J2DbmjZ2nA).

## What this repo is

A distribution package for one Hermes Agent skill. There is no build step and no
application runtime. The product is `skills/revenium/`; everything else is packaging,
docs, and tests.

Read [`CLAUDE.md`](CLAUDE.md) before changing anything under `skills/`. It documents the
architecture, the conventions, and — most importantly — the invariants the test suite
enforces and why each one exists.

## Getting set up

You need `bash`, `python3`, `sqlite3`, and the
[`revenium` CLI](https://github.com/revenium/revenium-cli). There is nothing to install
from this repo: no `package.json`, no `requirements.txt`, no lockfile.

```bash
git clone https://github.com/revenium/hermes-revenium.git
cd hermes-revenium
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The suite takes a few minutes. To iterate faster, run one class or one method:

```bash
python3 -m unittest tests.test_repository.RepositoryTests
python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native
```

To try a change on a real host, install from your clone. This copies
`skills/revenium/` into `~/.hermes/skills/revenium/` and runs the bundled installer:

```bash
bash install.sh
```

## The invariants

These are the ones that bite. All are enforced by tests, but knowing them up front saves a
round trip.

**State paths live in `scripts/common.sh` and nowhere else.** Adding a state file means
adding its variable there, above the `mkdir -p`. Never hardcode `~/.hermes/...` in a
calling script. `test_runtime_paths_are_hermes_native` fails the build otherwise.

**Metering must stay idempotent.** Re-running the cron can never double-report. The
append-only ledgers and the deterministic `--transaction-id` guarantee that together;
changes to session identity, splitting, or ledger writes must preserve it.

**Wire shape is pinned by golden fixtures.** `tests/fixtures/compat/*.golden.json` pin the
exact argv of `meter completion`, `meter tool-event`, `jobs create`, and `jobs outcome`.
Changing argv means changing a golden, deliberately, in the same commit.

**New CLI flags must be capability-probed and fail open.** Use `supports_flag` from
`common.sh`, so an older `revenium` CLI keeps metering exactly as it did before the flag
existed.

**Every in-session code path fails open.** A missing or corrupt status file, bad JSON, any
error at all — the answer is "not halted". A broken skill degrades to no enforcement, never
to a blocked agent.

**A halt is cleared only by `clear-halt.sh`.** Do not add a code path anywhere else that
sets `halted` back to false.

**Preserve each script's `set` flags.** `common.sh` and `hermes-report.sh` run `-uo
pipefail` on purpose, because they must survive per-item failures and keep logging.
Everything else runs `-euo pipefail`.

## Adding a script

Every new script in `skills/revenium/scripts/` must:

1. Source `common.sh`, then call `ensure_path` immediately — cron starts with an almost
   empty `PATH`.
2. Be added to the `expected` list in `tests/test_repository.py::test_expected_files_exist`.
3. Ship executable.
4. Parse under `bash -n`.

## Style

There is no linter or formatter. Match the neighbouring file.

- 2-space indent in Bash, 4-space in Python. LF endings, trailing newline.
- Quote and brace every expansion: `"${STATE_DIR}"`, `"${cmd[@]}"`.
- `[[ ... ]]` for conditionals, always.
- Resolve `SCRIPT_DIR` from `BASH_SOURCE[0]`, never `$0`.
- Build long CLI invocations as arrays; append optional flags conditionally.
- Comments explain *why*. Several in this codebase carry measured evidence and rejected
  alternatives — that is the record of why the code has its current shape. Preserve it when
  editing nearby.

## Documentation

Operator documentation lives in [`docs/`](docs/). Reference material that ships inside the
skill bundle and is read at runtime lives in `skills/revenium/references/` — `docs/` links
to it rather than restating it, because restating it is how the two fell out of sync
before.

Two tests police vocabulary: one greps every shipped text file for the product names this
skill was forked from, and one fails on any `budget-check` / `budget-status` reference under
`skills/`. It is `guardrail-check.sh` and `guardrail-status.json` now.

## Pull requests

- Branch from `main`; don't commit to it directly.
- Keep commits atomic, and explain *why* in the message body.
- Run the full suite before opening the PR, and say in the description what you ran.
- If you changed the halt block in `SKILL.md`, also run the manual survivability runbook at
  `skills/revenium/references/halt-survivability.md`.

## License

This project is [MIT licensed](LICENSE). By contributing, you agree that your
contributions will be licensed the same way.
