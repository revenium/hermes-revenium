# Testing Patterns

**Analysis Date:** 2026-05-12

This repo ships a single test file — `tests/test_repository.py` — using the Python standard-library `unittest` framework. The tests are **smoke / repository-shape tests, not behavior tests**: they assert that the right files exist, that `skills/revenium/SKILL.md` has the frontmatter Hermes requires, that `skills/revenium/scripts/common.sh` still points runtime state at `~/.hermes/`, that no legacy product names from the upstream fork leak in, and that every shell script parses cleanly. There is no execution of the cron pipeline, no real `state.db`, and no mocking — the tests run in milliseconds against the working tree.

## Test Framework

**Runner:**
- Python stdlib `unittest` — no `pytest`, no `tox`, no test-running config file.
- Discovery: `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Python version: whatever `python3` resolves to on the host. CI is not configured in-repo, so the framework targets "any reasonably modern Python 3 with `pathlib`, `subprocess`, `re`, `unittest`".

**Assertion library:**
- The methods on `unittest.TestCase` only: `assertTrue`, `assertIn`, `assertNotIn`, `assertEqual`. No `assertRaises`, no parametrization, no fixtures library.

**Run commands:**
```bash
# Run all tests (the canonical command from CLAUDE.md)
python3 -m unittest discover -s tests -p 'test_*.py' -v

# Run a single class
python3 -m unittest tests.test_repository.RepositoryTests

# Run a single method
python3 -m unittest tests.test_repository.RepositoryTests.test_runtime_paths_are_hermes_native

# Direct invocation (the file has `if __name__ == '__main__': unittest.main()`)
python3 tests/test_repository.py
```

There is no `make test`, no `npm test`, no `pytest` config — the `python3 -m unittest discover` form is the contract.

## Test File Organization

**Location:**
- Separate `tests/` directory at the repo root, not co-located with the code under test.
- Single file: `tests/test_repository.py`.
- `tests/__pycache__/` is gitignored (`.gitignore:1`).

**Naming:**
- File: `test_*.py` (required by the `-p 'test_*.py'` discovery pattern).
- Class: `RepositoryTests` (plural, ends in `Tests`).
- Method: `test_<imperative_assertion>` — e.g., `test_expected_files_exist`, `test_skill_frontmatter_has_hermes_metadata`, `test_no_legacy_branding_left`, `test_runtime_paths_are_hermes_native`, `test_shell_scripts_have_valid_syntax`.

**Structure:**
```
tests/
├── __pycache__/        # gitignored bytecode
└── test_repository.py  # the only test file in the repo
```

There is no `conftest.py`, no `fixtures/`, no `tests/helpers/`. New tests either go into a new method on `RepositoryTests` or a new `test_*.py` sibling file (with its own `TestCase` subclass).

## Test Structure

**Module-level constants** anchor every test to the repo root via `pathlib`:

```python
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
```

Source: `tests/test_repository.py:1-7`. The double-`parents` deref makes the tests insensitive to the cwd — they run identically from the repo root, from `tests/`, or from anywhere via absolute path.

**Suite organization:** one `unittest.TestCase` subclass (`RepositoryTests`) groups every assertion. Each method tests a single property of the repository.

**Patterns:**

- **Setup/teardown:** none. There is no `setUp`, no `tearDown`, no `setUpClass`. Each method is fully self-contained and only reads files via `pathlib`.
- **Iteration with informative failure messages:** loops include the offending path in the assertion message — e.g., `self.assertTrue(path.exists(), f'missing {path}')` (`tests/test_repository.py:28`). When a test fails, the message tells you exactly which file is wrong.
- **Collect-then-assert for grep-style checks:** `test_no_legacy_branding_left` builds an `offenders` list, then asserts it's empty (`tests/test_repository.py:38-49`). This surfaces *all* offending paths in one run rather than failing on the first.
- **`subprocess` for tooling checks:** `test_shell_scripts_have_valid_syntax` shells out to `bash -n <script>` (`tests/test_repository.py:57-70`). This is the only test that depends on an external binary — `bash` must be on `PATH`.

## What's Tested

| Test method | Asserts | File reference |
|-------------|---------|----------------|
| `test_expected_files_exist` | All shipped files are present at their expected paths — `README.md`, `docs/installation.md`, `examples/setup-local.sh`, `skills/revenium/SKILL.md`, the two `references/` docs, and every `scripts/*.sh` file. | `tests/test_repository.py:11-28` |
| `test_skill_frontmatter_has_hermes_metadata` | `skills/revenium/SKILL.md` contains the literal substrings `name: revenium`, `metadata:`, `hermes:`, and `category: devops`. Substring-level, not YAML-parsed. | `tests/test_repository.py:30-35` |
| `test_no_legacy_branding_left` | No file with extension `.md`, `.sh`, `.py`, `.txt`, `.json`, `.yml`, `.yaml` contains the upstream-fork product names matched by the regex on `tests/test_repository.py:47`. The test file itself is exempted by name. | `tests/test_repository.py:37-49` |
| `test_runtime_paths_are_hermes_native` | `skills/revenium/scripts/common.sh` contains the literal strings `.hermes` and `state/revenium`, and does *not* contain `.openclaw`. Locks the cron half into writing runtime state under `~/.hermes/state/revenium/`. | `tests/test_repository.py:51-55` |
| `test_shell_scripts_have_valid_syntax` | Every `*.sh` file under `skills/revenium/scripts/` parses with `bash -n` (rc=0). Catches typos, unclosed quotes, missing `fi`/`done` without running the script. | `tests/test_repository.py:57-70` |

## What's NOT Tested

By design — these are intentionally out of scope and would require fixtures the repo doesn't ship:

- **The metering pipeline.** `skills/revenium/scripts/hermes-report.sh` is not exercised. There is no fixture `state.db`, no recorded session data, no replay of `revenium meter completion` calls, no assertion on ledger delta math, and no test of the provider-inference heredocs.
- **Budget evaluation logic.** `skills/revenium/scripts/budget-check.sh` is not run. The `exceeded` / `halted` / `haltedAt` transition logic in the embedded Python heredoc (`budget-check.sh:43-94`) has no direct coverage — only the script's bash syntax is checked.
- **Halt clearing.** `skills/revenium/scripts/clear-halt.sh` is not executed against a real `budget-status.json`.
- **Cron installation.** `install-cron.sh` / `uninstall-cron.sh` are not invoked. The generated `crontab` line is not validated.
- **The Revenium CLI integration.** No mock of `revenium meter completion`, `revenium config show`, or `revenium alerts budget get`. The flags constructed in `hermes-report.sh:216-249` are not asserted.
- **Cross-shell portability.** Tests only check Bash syntax, not POSIX `sh` compatibility.
- **JSON schema validity.** `test_skill_frontmatter_has_hermes_metadata` is substring-based — it would pass even if the YAML were technically malformed (e.g., wrong indentation under `metadata:`).

If you need behavioral coverage of the cron pipeline, add it as a new `test_*.py` file that builds a temp dir, drops a fixture `state.db` and `config.json` in it, runs the script with `HERMES_HOME=<tmpdir>`, and asserts on the resulting `budget-status.json` and `ledger`. The infrastructure for that does not exist yet.

## Mocking

**None.** This is a deliberate choice — these are repository-shape tests, not behavior tests. No `unittest.mock`, no patching, no monkeypatching, no test doubles. The closest thing to a "fake" is `subprocess.run(['bash', '-n', ...])`, which is the real `bash` parsing the real script.

**What to mock when adding behavior tests (if/when they arrive):**
- The `revenium` CLI: shadow it with a fake script on `PATH` that records its argv and emits canned stdout. The reporter calls it via `command -v revenium` + `"${cmd[@]}"` — no Python-side imports to patch.
- The `state.db`: create a real SQLite file with the schema expected by `hermes-report.sh:45-53` and seed it with rows.
- Time: avoid mocking — instead, write timestamps explicitly into the fixture and let the script consume them.

**What NOT to mock:**
- The file system. Use `tempfile.TemporaryDirectory()` and point `HERMES_HOME` / `REVENIUM_STATE_DIR` at it. Real files are cheap and catch real bugs.
- `python3` heredocs. They run as part of the bash script — exercising the script also exercises them.

## Fixtures and Factories

**None ship with the repo.** No `tests/fixtures/`, no factory helpers, no sample `state.db`, no sample `config.json`. The only static "fixture" is the working tree itself — `ROOT` and `SKILL` point at the live source.

If you add fixtures, the conventional location based on the existing layout would be `tests/fixtures/` with subdirectories per scenario.

## Coverage

**Requirements:** none enforced. No `coverage.py`, no `--cov` flag, no minimum percentage gate.

**Effective coverage:** structural only — the tests verify that files exist and shell scripts parse, which protects against accidental deletion/rename and against syntax-breaking edits, but not against logic regressions in the cron pipeline.

**View coverage (if you opt in locally):**
```bash
python3 -m pip install coverage
python3 -m coverage run -m unittest discover -s tests -p 'test_*.py'
python3 -m coverage report
```
This isn't part of the workflow and shouldn't be committed as a requirement.

## Test Types

**Unit tests:** none in the traditional sense — there are no isolated function-level tests because there are no Python production modules. The "units" under test are repository invariants and shell-script files.

**Integration tests:** none. The cron pipeline (`cron.sh` → `hermes-report.sh` + `budget-check.sh`) is never executed end-to-end by the test suite.

**Repository / smoke tests:** all five tests in `tests/test_repository.py`. They are fast (sub-second), deterministic, and run with zero external dependencies beyond `python3` and `bash`.

**E2E tests:** not used. `examples/setup-local.sh` is the closest thing to an E2E driver, but it's a developer convenience for installing into a real `~/.hermes/`, not part of the test suite.

## Common Patterns

**Path resolution from the test file:**
```python
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'revenium'
```
Always derive paths from `__file__` — never rely on `os.getcwd()`.

**Substring assertion against a text file:**
```python
text = (SKILL / 'SKILL.md').read_text()
self.assertIn('name: revenium', text)
self.assertIn('category: devops', text)
```
Source: `tests/test_repository.py:30-35`. Cheap, robust to YAML formatting changes, and easy to grow when you need to enforce a new contract field.

**Forbidden-substring assertion via regex over the tree:**
```python
offenders = []
for path in ROOT.rglob('*'):
    if not path.is_file():
        continue
    if path.suffix not in {'.md', '.sh', '.py', '.txt', '.json', '.yml', '.yaml'}:
        continue
    if path.name == 'test_repository.py':
        continue
    text = path.read_text(errors='ignore')
    if re.search(r'<forbidden_pattern>', text):
        offenders.append(str(path.relative_to(ROOT)))
self.assertEqual(offenders, [], f'found ... in: {offenders}')
```
Source: `tests/test_repository.py:37-49`. Note `errors='ignore'` on `read_text` so binary-ish files don't crash the walk, and the explicit suffix allowlist so we don't scan caches or `.git`. When adding new file types to the guard, extend the suffix set; when adding new forbidden strings, extend the regex alternation.

**Shell-syntax assertion via `bash -n`:**
```python
scripts = sorted((SKILL / 'scripts').glob('*.sh'))
self.assertTrue(scripts, 'no shell scripts found')
for script in scripts:
    result = subprocess.run(
        ['bash', '-n', str(script)],
        capture_output=True,
        text=True,
    )
    self.assertEqual(
        result.returncode,
        0,
        f'syntax error in {script.name}: {result.stderr}',
    )
```
Source: `tests/test_repository.py:57-70`. `capture_output=True` plus `text=True` is the modern (Python 3.7+) idiom; don't fall back to `stdout=subprocess.PIPE`.

**Async testing:** not applicable — no async code anywhere in the repo.

**Error testing:** not present. There are no `assertRaises` calls because the tests don't exercise behavior that can throw — `read_text(errors='ignore')` and `path.exists()` don't raise on missing/binary content.

## Adding New Tests

When you need to assert a new repository invariant:

1. Add a new method to `RepositoryTests` in `tests/test_repository.py`. Name it `test_<assertion>`.
2. Anchor paths via `ROOT` or `SKILL` (already imported).
3. Prefer collect-then-assert (build a list of offenders, then `assertEqual(offenders, [])`) for any check that scans multiple files — it surfaces every failure in one run.
4. If you're adding a behavior test that actually executes a script:
   - Build a temp `HERMES_HOME` with `tempfile.TemporaryDirectory()`.
   - Pass it via env: `subprocess.run([...], env={**os.environ, 'HERMES_HOME': tmp, 'REVENIUM_STATE_DIR': f'{tmp}/state/revenium'}, ...)`.
   - Stub external CLIs (`revenium`, `sqlite3`) by placing fakes earlier on `PATH` in the env dict.
   - Don't use real network / real Revenium — there's no API key in CI.

When you ship a new script under `skills/revenium/scripts/`:

1. Add its path to the `expected` list in `test_expected_files_exist` (`tests/test_repository.py:12-26`) — otherwise the test passes vacuously for the new file.
2. `test_shell_scripts_have_valid_syntax` will pick it up automatically via the `*.sh` glob.
3. `test_no_legacy_branding_left` will scan it automatically as long as it ends in `.sh`.

---

*Testing analysis: 2026-05-12*
