# Codebase Concerns

**Analysis Date:** 2026-05-12

## Tech Debt

**Halt-message contract drift between SKILL.md and budget-check.sh:**
- Issue: The user-facing halt string is duplicated in two places with different wording. `skills/revenium/SKILL.md:35` instructs the agent to emit `> Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`, while `skills/revenium/scripts/budget-check.sh:103` builds a notifier message reading `Budget halt active. Spent $${CURRENT_VALUE} of $${THRESHOLD_VALUE} (${PERCENT}%). All autonomous operations are now stopped. To resume: bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`. The Hermes spec (per CLAUDE.md) describes the SKILL.md string as contractual. Nothing forces the two to stay in sync.
- Files: `skills/revenium/SKILL.md:35`, `skills/revenium/scripts/budget-check.sh:103`
- Impact: Silent UX drift. Future edits to one will not propagate to the other; tests do not assert either string.
- Fix approach: Pull the halt string template into a shared location (e.g., `skills/revenium/references/halt-message.md`) or add a test asserting both files contain `Budget …halt…active` style markers and the `clear-halt.sh` path.

**Provider inference is string-matching against model names:**
- Issue: `skills/revenium/scripts/hermes-report.sh:126-165` infers provider via `'claude' in model`, `'gpt' in model or 'o1-' in model or 'o3-' in model`, `'gemini' in model`, `'grok' in model or 'x-ai' in model`, `'deepseek' in model`, `'llama' in model or 'mistral' in model`. Any new model family (e.g., Anthropic's next codename, OpenAI `o4-`, Google "nano-banana") is silently classified `unknown`. The OpenRouter branch repeats the same brittle string match against a slightly different vocabulary, and the Bedrock branch only handles `claude` — every other Bedrock model becomes `aws`.
- Files: `skills/revenium/scripts/hermes-report.sh:126-165`
- Impact: Misattributed or `unknown`-providered transactions inside Revenium reports.
- Fix approach: Extract the mapping into a single Python dict keyed by canonical model prefixes; add a small `tests/test_provider_inference.py` that pins the mapping table and exercises a representative model name from each provider plus OpenRouter and Bedrock variants. Treat the table as the public contract.

**Provider-prefix stripping is also positional:**
- Issue: `skills/revenium/scripts/hermes-report.sh:116-124` strips known prefixes (`global.`, `anthropic.`, `openai.`, `google.`, `x-ai.`) and splits on the first `/` to normalize the model string. New routing schemes (e.g., Bedrock cross-region prefixes like `us.`, `eu.`, additional vendor.) will leak prefixes into the reported `--model`.
- Files: `skills/revenium/scripts/hermes-report.sh:116-124`
- Impact: Inconsistent model strings in Revenium reports.
- Fix approach: Replace the prefix list with a regex like `^([a-z0-9-]+\.)+` after splitting on `/`, or pin the list explicitly with a coverage test.

**Ledger format is positional and unversioned:**
- Issue: `~/.hermes/state/revenium/revenium-hermes.ledger` lines are `HERMES:<session_id>:<total_tokens>:<unix_ts>` per CLAUDE.md / `skills/revenium/scripts/hermes-report.sh:70`, `:78`, `:170`, `:256`. There is no schema version, no header, no comment lines, and the parser is `grep` + `cut -d:`. A session_id containing `:` (currently UUID-shaped in Hermes but not guaranteed) would silently corrupt parsing. Future fields cannot be added without breaking all deployed installs because rotation is by re-writing in place.
- Files: `skills/revenium/scripts/hermes-report.sh:70,78,170,256`
- Impact: Future format changes are not backward-compatible; cannot detect upgraded vs. legacy ledger lines.
- Fix approach: Prefix lines with a version marker (`HERMES:v1:…`) or switch to TSV/JSONL. Add a parse step that ignores unknown-version lines rather than crashing.

**Cron pipeline silently masks both child failures:**
- Issue: `skills/revenium/scripts/cron.sh:17-18` runs `hermes-report.sh "$@" || true; budget-check.sh "$@" || true`. The `|| true` is there to keep one failing half from disabling the other, but it also means crons that have been broken for hours show success in syslog. There is no per-step exit-code surfacing into the log.
- Files: `skills/revenium/scripts/cron.sh:17-18`
- Impact: A broken reporter (e.g., schema change, CLI flag removal) is undetectable from the cron exit code; only `revenium-metering.log` reveals it.
- Fix approach: Emit a final summary log line including each step's exit code, e.g., `info "cron: report=$rc1 budget=$rc2"`, so `grep -E "cron: report=[^0]" log` surfaces silent failures.

**Two `set` regimes across the script set:**
- Issue: `common.sh:4` and `hermes-report.sh:6` use `set -uo pipefail` (no `-e`), while `cron.sh:2`, `budget-check.sh:2`, `clear-halt.sh:2`, `install-cron.sh:2`, `uninstall-cron.sh:2` use `set -euo pipefail`. The choice is intentional for `hermes-report.sh` (per-session loop should not abort on a single Python heredoc failure), but the discrepancy is undocumented and easy to "fix" wrongly during cleanup.
- Files: `skills/revenium/scripts/hermes-report.sh:6`, `skills/revenium/scripts/common.sh:4`, plus the five `-euo` scripts above
- Impact: A future contributor adding `set -e` to `hermes-report.sh` would cause one bad session to skip every subsequent session in the same cron tick.
- Fix approach: Add a one-line comment at the top of `hermes-report.sh` explaining why `-e` is deliberately absent; mirror the comment in `common.sh`.

**`ensure_path` mutates global `PATH` repeatedly:**
- Issue: `skills/revenium/scripts/common.sh:20-28` prepends each candidate directory to `PATH` whether it is already present or not. Repeated sourcing (cron tick + any script that calls `ensure_path`) leaves an ever-growing `PATH`. In a per-minute cron context the leak is bounded by process lifetime, so this is theoretical for cron, but a Hermes session that sources `common.sh` many times in one shell does duplicate entries.
- Files: `skills/revenium/scripts/common.sh:20-28`
- Impact: Cosmetic / minor performance.
- Fix approach: De-dupe with `case ":$PATH:" in *":$p:"*) ;; *) export PATH="$p:$PATH" ;; esac`.

## Known Bugs

**Recently fixed (still worth pinning with tests) — Python heredoc quoting in `budget-check.sh`:**
- Symptoms: Halt notifications historically rendered `Spent $? of $?` because unquoted heredocs allowed bash to expand Python f-string format specs.
- Files: `skills/revenium/scripts/budget-check.sh:47` (now uses `<<'PY'` quoted heredoc and env-var passing)
- Trigger: Any halt transition with a real budget number.
- Workaround: Fixed in commit `43c52e4`.
- Residual concern: No test pins the rendered halt-notification string. The fix is correct now, but a future refactor that converts the heredoc back to an unquoted form would regress silently. Recommend a `tests/test_budget_check.py` that runs `budget-check.sh` against a stub `revenium` binary and asserts the formatted summary line is not literally `?`.

**`clear-halt.sh` uses `${VAR@Q}` and an unquoted Python literal mix:**
- Symptoms: `skills/revenium/scripts/clear-halt.sh:13-27` opens an *unquoted* heredoc (`<<PY`) but expands `${BUDGET_STATUS_FILE@Q}` inside, relying on bash to quote the path. The heredoc body also contains a literal multi-line `'\n'` written as a raw newline inside `path.write_text(... + '\n')` (lines 24-25 in the source view: the `\n` is on its own line inside the heredoc). This works today but is fragile: any contributor adding a `$` or backtick inside the Python body will hit unwanted bash expansion. Compare with `budget-check.sh`'s `<<'PY'` + env-var passing — that is the safer pattern from commit `43c52e4`.
- Files: `skills/revenium/scripts/clear-halt.sh:13-27`
- Trigger: Adding any new Python content using `$` or `` ` `` to this heredoc.
- Workaround: None needed today; documented here as a latent bug.
- Fix approach: Convert to `BUDGET_STATUS_FILE="${BUDGET_STATUS_FILE}" python3 - <<'PY'` matching `budget-check.sh:47-94`.

**`hermes-report.sh` parses `sqlite3` pipe-separated output without `-separator`:**
- Symptoms: `skills/revenium/scripts/hermes-report.sh:45-53` runs `sqlite3 "${STATE_DB}" "SELECT … FROM sessions …"` and pipes the default `|`-separated output into `while IFS='|' read -r …`. If any model name, source, or billing_provider value contains a `|`, the column alignment shifts and the row is silently mis-parsed (provider becomes part of model, token counts shift, etc.). The same query has no defense against embedded newlines in any text column.
- Files: `skills/revenium/scripts/hermes-report.sh:45-63`
- Trigger: A model identifier or billing_provider string containing `|` or `\n`. Unlikely with current providers, but Hermes's `state.db` schema is implicit and not contractually frozen.
- Workaround: None today; treat any future schema additions as risky.
- Fix approach: Use `sqlite3 -separator $'\x1f'` (ASCII unit separator) and update the `IFS=$'\x1f'` accordingly, or pivot to `sqlite3 -json` and parse with Python.

**Empty `cache_read` / `cache_write` / `reasoning_tokens` columns crash arithmetic:**
- Symptoms: `skills/revenium/scripts/hermes-report.sh:65,98-101` does `total_tokens=$((input_tokens + output_tokens))` and `int(${cache_read} * ${ratio})`. If `state.db` returns an empty string for any numeric column (NULL → empty in sqlite3 default output), bash arithmetic emits `bash: ((: + : syntax error`, the Python heredoc raises `SyntaxError`, the `2>/dev/null || echo "0"` swallows it, and the session is silently skipped. `set -uo pipefail` will not trigger `-e`-style abort because of the explicit fallbacks.
- Files: `skills/revenium/scripts/hermes-report.sh:65,98-101,116-124,126-165,173-197`
- Trigger: Any NULL or empty numeric column in `sessions`.
- Workaround: None today; relies on Hermes always populating these columns.
- Fix approach: Coalesce NULLs in SQL (`COALESCE(input_tokens, 0)` for every numeric column), or default empty strings to `0` in bash with `${input_tokens:-0}` before arithmetic.

**`reasoning_tokens` is selected but never used:**
- Symptoms: `skills/revenium/scripts/hermes-report.sh:46-48` selects `reasoning_tokens` from the sessions table, but it never appears in the `revenium meter completion` argv (`hermes-report.sh:216-235`). Reasoning-token-heavy models (o1, o3, Claude with thinking) under-report total cost.
- Files: `skills/revenium/scripts/hermes-report.sh:46,63,216-235`
- Trigger: Any model that produces non-zero `reasoning_tokens`.
- Workaround: None — the data is being collected and discarded.
- Fix approach: Either drop the column from the SELECT (and the `read -r` binding) to make the omission explicit, or add a `--reasoning-tokens "${delta_reasoning}"` flag once the Revenium CLI supports it. Pick one and document.

## Security Considerations

**Cron persistence is the intended behavior but the security scanner flags it correctly:**
- Risk: `install-cron.sh` writes a `* * * * *` cron entry into the user's crontab that sources `${ENV_FILE}` and exports it before running shell. Anyone who can write `~/.hermes/state/revenium/env` can inject environment variables into a minute-cadence root-of-user shell.
- Files: `skills/revenium/scripts/cron.sh:10-15`, `skills/revenium/scripts/install-cron.sh:26`
- Current mitigation: `${ENV_FILE}` lives in user-owned `${HERMES_HOME}/state/revenium/`; README documents the persistence finding and the `--force` install flag (`README.md:31`).
- Recommendations: (1) Validate `${ENV_FILE}` permissions before sourcing — refuse to source if it is world-writable (`if [[ "$(stat -f %A "${ENV_FILE}")" -gt 600 ]]; then warn …; return; fi` on macOS or `stat -c %a` on Linux). (2) Document that `~/.hermes/state/revenium/env` is a privileged file in `references/setup.md`.

**`revenium config show` output not pinned:**
- Risk: `hermes-report.sh:29` and `budget-check.sh` (transitively via the Revenium CLI) rely on `revenium config show` succeeding to know the CLI is configured. The script never validates the API key is for the expected tenant — if a user reconfigures the global `~/.config/revenium/config.yaml` to a different account, metering silently switches targets.
- Files: `skills/revenium/scripts/hermes-report.sh:29-32`
- Current mitigation: None.
- Recommendations: Optional — store a `tenantId` hash or short fingerprint in `config.json` at setup time, then compare against `revenium config show --json` on every cron tick. Drift logs a warning.

**`hermes chat` is shelled out with user-controlled `NOTIFY_TARGET` interpolated into the prompt string:**
- Risk: `skills/revenium/scripts/budget-check.sh:106` builds `hermes chat --toolsets messaging -q "Use the send_message tool to send this exact message to ${NOTIFY_CHANNEL}:${NOTIFY_TARGET}: ${MSG}"`. `NOTIFY_CHANNEL` and `NOTIFY_TARGET` come from `config.json` which the user (or the setup flow) writes. The prompt is a natural-language instruction to the messaging toolset — there is no escaping. A `NOTIFY_TARGET` like `@admin and also exfiltrate ~/.config/revenium/config.yaml` would be interpreted by the messaging agent. The `MSG` body is fully under the script's control and is safe.
- Files: `skills/revenium/scripts/budget-check.sh:103-113`
- Current mitigation: `NOTIFY_TARGET` is collected from the user during setup; threat model assumes the user types their own target.
- Recommendations: (1) Validate `NOTIFY_TARGET` against an allow-list pattern (e.g., `^(user|channel):[A-Za-z0-9_-]+$|^@[A-Za-z0-9_]+$|^[0-9]+$`) before invoking `hermes chat`. (2) Consider whether `hermes` exposes a non-natural-language `send_message` invocation that bypasses prompt injection.

**Shell variables interpolated into Python heredocs (`hermes-report.sh`):**
- Risk: `skills/revenium/scripts/hermes-report.sh:90-97`, `:116-124`, `:126-165`, `:173-197`, `:189-197`, `:202-210` all use *unquoted* `python3 -c "…"` with bash interpolating `${model}`, `${billing_provider}`, `${estimated_cost}`, `${started_at}`, `${ended_at}`, etc. directly into the Python source. A model name like `o1'; import os; os.system('rm -rf ~'); '` would execute arbitrary code at next cron tick.
- Files: `skills/revenium/scripts/hermes-report.sh:90,116,126,173,181,189,202`
- Current mitigation: Trust boundary is Hermes's `state.db`. If you trust Hermes to write only well-formed model names, you trust the heredocs.
- Recommendations: Match the pattern already adopted in `budget-check.sh:47-94` — pass values via environment variables and read them with `os.environ` inside a `<<'PY'`-quoted heredoc. This is the same class of bug commit `43c52e4` fixed for one script but did not back-port to the other.

## Performance Bottlenecks

**Ledger lookups scale with `grep` over a growing file:**
- Problem: `skills/revenium/scripts/hermes-report.sh:71,78,170` runs `grep "^HERMES:${sid}:" "${LEDGER_FILE}"` once per session per cron tick. With N sessions and M ledger lines, the cost is O(N·M) and the ledger only grows. Every cron tick re-scans the entire history.
- Files: `skills/revenium/scripts/hermes-report.sh:71,78,170`
- Cause: Append-only flat file, no rotation, no index.
- Improvement path: (1) `tac "${LEDGER_FILE}" | grep -m1 "^HERMES:${sid}:"` collapses the duplicate scans on lines 78 and 170 into one. (2) Add log rotation: keep only the most recent line per session in a compacted ledger file (idempotency check still works because the ledger key includes total_tokens).

**Python subprocess startup is hot:**
- Problem: `hermes-report.sh` invokes `python3 -c "…"` between 8 and 11 times per session per cron tick (lines 38, 90, 98-101, 116, 126, 173, 181, 189, 202, 255). Per-minute cron with 10 active sessions = ~100 Python startups/minute.
- Files: `skills/revenium/scripts/hermes-report.sh:38,90,98-101,116,126,173,181,189,202,255`
- Cause: Each value transformation spawns a fresh Python interpreter.
- Improvement path: Consolidate into a single `python3 -` script per session that reads the sqlite row from stdin (or directly opens `${STATE_DB}` with `sqlite3` module) and prints all derived values as `KEY=value` lines that the shell loop sources with `eval` or `read`. Or rewrite the whole reporter in Python — there is essentially no bash idiom in the loop that Python cannot do natively.

## Fragile Areas

**`state.db` schema is an implicit cross-repo contract:**
- Files: `skills/revenium/scripts/hermes-report.sh:45-53`
- Why fragile: The SELECT names 13 columns from `sessions` — `id, model, source, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd, api_call_count, started_at, ended_at, billing_provider`. If Hermes renames a column, drops one, or adds a column before another in the row order, the `while IFS='|' read -r …` unpacking shifts and every metric ships to the wrong field at Revenium.
- Safe modification: Pin the schema in a test fixture (a known-good `state.db` snapshot) and add a `tests/test_state_db_schema.py` that asserts the expected columns exist before each release.
- Test coverage: None.

**`revenium meter completion` CLI flag shape is an implicit contract:**
- Files: `skills/revenium/scripts/hermes-report.sh:216-249`
- Why fragile: Twenty-plus long-form flags are hardcoded (`--input-tokens`, `--cache-creation-tokens`, `--total-cost`, `--transaction-id`, `--is-streamed`, …). If the Revenium CLI renames or removes any of these, `hermes-report.sh` fails silently (the exit code is captured and logged but no out-of-band alert fires) and metering stops.
- Safe modification: (1) Add a `revenium meter completion --help` parse step at the top of `hermes-report.sh` that asserts each expected flag is supported; warn-and-skip if any are missing. (2) Pin the minimum Revenium CLI version in `README.md` (`Prerequisites`) and document the flag dependency. (3) Consider whether the Revenium CLI exposes a JSON-flagged form less likely to drift than long-options.
- Test coverage: None. `tests/test_repository.py` only runs `bash -n` syntax checks.

**`budget-status.json` / `config.json` shape is the cron↔SKILL.md public interface:**
- Files: `skills/revenium/scripts/budget-check.sh:56-82`, `skills/revenium/scripts/clear-halt.sh:13-26`, `skills/revenium/SKILL.md:56-89`
- Why fragile: CLAUDE.md explicitly calls these out as the public interface, but nothing tests the shape. `SKILL.md` instructs the agent to read fields `currentValue`, `threshold`, `percentUsed`, `exceeded`, `halted`, `lastChecked` — but `budget-check.sh` writes whatever `revenium alerts budget get --json` returns plus a few computed fields. The cron does not assert `percentUsed` exists in the upstream response, even though `SKILL.md:58` tells the agent to read it.
- Safe modification: (1) Add a `tests/test_budget_status_shape.py` that simulates a `revenium alerts budget get --json` response, runs `budget-check.sh` against a temp `BUDGET_STATUS_FILE`, and asserts all SKILL.md-named fields are present and correctly typed. (2) Have `budget-check.sh` compute `percentUsed` locally rather than trusting upstream.
- Test coverage: None.

**Halt-message in `SKILL.md` is enforced only by prompting:**
- Files: `skills/revenium/SKILL.md:24-46`
- Why fragile: The "ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)" instruction is verbatim text inside a markdown file. Hermes itself does not enforce the halt — it is the LLM's compliance with the prompt that does. A model regression, a prompt-truncation edge case, a context-overflow drop of the SKILL.md preamble, or a competing higher-priority instruction can override it.
- Safe modification: Treat the halt-string and the surrounding "ABSOLUTE FIRST" wording as load-bearing. Any edit needs to be reviewed against the Hermes spec.
- Test coverage: `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata` covers the frontmatter only — not the halt-block wording or its position in the file.

**No JSON validation on `config.json` reads:**
- Files: `skills/revenium/scripts/budget-check.sh:10-24`, `skills/revenium/scripts/hermes-report.sh:36-39`
- Why fragile: Both scripts read `config.json` with `json.load(open(...))`. A user hand-edit that produces invalid JSON raises `json.JSONDecodeError` from inside the Python heredoc — `hermes-report.sh:38`'s `2>/dev/null || true` swallows it (`ORG_NAME` ends up empty, metering continues without org attribution), while `budget-check.sh:32`'s subsequent CLI call may proceed with empty `ALERT_ID`, fail the `revenium alerts budget get` call, and never update `budget-status.json` — leaving stale `halted` state.
- Safe modification: Add a `validate_config` step that exits early with a clear error if `config.json` is invalid; surface the error in the metering log rather than swallowing it.
- Test coverage: None.

## Scaling Limits

**Ledger file growth is unbounded:**
- Current capacity: Each metered transaction appends one line. At 10 sessions × per-minute cron × 1440 minutes/day = up to 14,400 lines/day in the worst case (mostly skipped early via the duplicate-key check, but each cron tick re-greps the entire file).
- Limit: At ~10 MB the `grep` cost becomes noticeable on slow disks; at ~100 MB the per-cron-tick latency may approach the 60-second cron interval.
- Files: `skills/revenium/scripts/hermes-report.sh:71,78,170,256`
- Scaling path: Rotate the ledger weekly into `revenium-hermes.ledger.YYYY-WW`, keep only the last 2-4 weeks active. Update the lookups to scan recent ledger only. Or move to SQLite with the same idempotency key as a primary key.

## Dependencies at Risk

**`revenium` CLI:**
- Risk: External CLI tool whose flag surface is treated as stable but is not pinned to a specific version anywhere in this repo. `README.md:9` says `brew install revenium/tap/revenium` without a version constraint.
- Impact: A CLI update that removes `--cache-creation-tokens` or renames `--total-cost` to `--cost` breaks all metering silently — the cron logs `warn "Failed: …"` but the cron exit code is still 0 (`cron.sh:17`).
- Migration plan: Pin a minimum version in `README.md`; assert it at the top of `hermes-report.sh` with `revenium --version` parse.

**`hermes` CLI for halt notifications:**
- Risk: `budget-check.sh:105-113` shells out to `hermes chat --toolsets messaging -q "<natural-language prompt>"`. The `--toolsets` flag, the `-q` quiet flag, and the "Use the send_message tool" prompt convention are all implicit contracts with Hermes.
- Impact: A Hermes CLI release that renames the messaging toolset, drops `-q`, or changes the tool name `send_message` will break halt notifications silently. The script's only feedback path is `echo "Failed to send halt notification via Hermes …"` to stdout, which the cron pipes to `${LOG_FILE}`.
- Migration plan: Pin a minimum Hermes version in `README.md` / `docs/installation.md`. Add an integration test that runs `hermes chat --help` and asserts `--toolsets messaging` is documented.

**`python3` (no minimum version pin):**
- Risk: `hermes-report.sh` and `budget-check.sh` use f-strings (3.6+), `datetime.timezone.utc` (3.2+), and `pathlib.Path` (3.4+). All scripts will work on Python 3.6+, but no `python3 --version` check exists.
- Impact: A user on Python 3.5 (rare but possible on long-lived servers) gets cryptic syntax errors swallowed by `2>/dev/null`.
- Migration plan: Either assert `python3 -c 'import sys; assert sys.version_info >= (3, 8)'` at top of each script, or document `Python ≥ 3.8` explicitly in `README.md:11`.

**`sqlite3` CLI:**
- Risk: Hard dependency on `sqlite3` binary at `hermes-report.sh:17-19`. macOS ships sqlite3; many minimal Linux containers do not.
- Impact: Cron silently skips metering with a `warn` log (`hermes-report.sh:18`).
- Migration plan: Mention `sqlite3` requirement on Linux explicitly in `docs/installation.md` and `README.md`.

## Missing Critical Features

**No CI:**
- Problem: There is no `.github/workflows/`, `.circleci/`, `.gitlab-ci.yml`, or any other CI config. `tests/test_repository.py` exists with five test methods (file existence, frontmatter shape, no-legacy-branding, runtime-paths, bash syntax) but is never run automatically.
- Blocks: Catching regressions on PR. The bug fixed by commit `43c52e4` ("budget-check.sh had three runtime bugs hiding behind `2>/dev/null`") is exactly the class CI would catch — the `bash -n` syntax test was added in that commit but is run only when a contributor remembers `python3 -m unittest discover`.
- Fix approach: Add a minimal `.github/workflows/test.yml` that runs `python3 -m unittest discover -s tests -p 'test_*.py' -v` on push and PR. Optionally shellcheck the scripts.

**No shellcheck:**
- Problem: 519 lines of bash with no static analysis. `set -uo pipefail` catches some classes of error but cannot catch unquoted heredocs (the bug `43c52e4` fixed) or unsafe variable interpolation into Python heredocs (the latent bug in `hermes-report.sh`).
- Blocks: Detection of quoting bugs, unset-variable bugs, and word-splitting bugs.
- Fix approach: Add `shellcheck skills/revenium/scripts/*.sh` to CI. Accept that some `# shellcheck disable=…` directives will be needed (e.g., the deliberate unquoted Python heredocs in `hermes-report.sh` — though those should be fixed, not disabled).

**No end-to-end test of the cron pipeline:**
- Problem: `tests/test_repository.py` does not exercise `cron.sh`, `hermes-report.sh`, or `budget-check.sh` at runtime. There is no fixture `state.db` and no stub `revenium`/`hermes` CLI.
- Blocks: Detecting that the cron pipeline still produces a well-formed `budget-status.json`, still writes ledger lines, still calls the Revenium CLI with the expected argv.
- Fix approach: Add a `tests/test_cron_pipeline.py` that (1) seeds a tmp `${HERMES_HOME}` with a fixture `state.db` and `config.json`, (2) puts shim `revenium` and `hermes` scripts on `PATH` that record their argv to a file, (3) runs `bash cron.sh`, (4) asserts on the recorded argv and on the resulting `budget-status.json` / ledger.

**No linter or formatter on bash:**
- Problem: CLAUDE.md notes "There is no linter or formatter wired up." Style drift is a real risk in a 519-line bash codebase.
- Fix approach: Add `shfmt -d skills/revenium/scripts/*.sh` to the test suite as an advisory step, or commit a `.editorconfig`.

**No `--dry-run` for `hermes-report.sh`:**
- Problem: There is no way to see what would be reported without actually shipping to Revenium. Operators debugging metering issues have to read the log after-the-fact.
- Blocks: Local development and troubleshooting.
- Fix approach: Honor a `--dry-run` flag passed via `cron.sh "$@"` that builds the argv but does not invoke `revenium meter completion` (just logs it).

## Test Coverage Gaps

**Provider inference logic:**
- What's not tested: `hermes-report.sh:126-165` provider-mapping table.
- Files: `skills/revenium/scripts/hermes-report.sh:126-165`
- Risk: Adding a new model family (or breaking the existing mapping during a refactor) ships unattributed transactions to Revenium with no test signal.
- Priority: High.

**Ledger idempotency:**
- What's not tested: Re-running `hermes-report.sh` against the same `state.db` should produce zero new ledger lines. CLAUDE.md calls this out as load-bearing.
- Files: `skills/revenium/scripts/hermes-report.sh:70-85`
- Risk: A refactor of the ledger-lookup logic could silently double-report.
- Priority: High.

**Halt transition vs. existing halt:**
- What's not tested: `budget-check.sh:72-82` distinguishes a new halt (sends notification) from an existing halt (silent). Commit `43c52e4` fixed bugs in this code path. No regression test pins the behavior.
- Files: `skills/revenium/scripts/budget-check.sh:64-82,98-117`
- Risk: A future edit could re-introduce duplicate notifications on every cron tick during a sustained halt.
- Priority: High.

**`clear-halt.sh` happy path and idempotency:**
- What's not tested: Running `clear-halt.sh` when no halt is active must say "No halt is currently active." and exit 0; running it when one is active must flip `halted: false` and remove `haltedAt`.
- Files: `skills/revenium/scripts/clear-halt.sh:18-26`
- Risk: Low (the script is 27 lines) but currently no test exists.
- Priority: Medium.

**`install-cron.sh` re-run idempotency:**
- What's not tested: Calling `install-cron.sh` twice must not produce two cron entries. The script checks for `hermes-revenium-metering` in the existing crontab (`install-cron.sh:28-32`), but a test could lock that in.
- Files: `skills/revenium/scripts/install-cron.sh:28-32`
- Risk: A future edit to the marker comment (currently `# hermes-revenium-metering`) could leave the user with multiple cron entries.
- Priority: Medium.

**Legacy branding test scope:**
- What's tested: `tests/test_repository.py:37-49` greps for the forked-tool product-name regex defined on `tests/test_repository.py:47`. The repo was forked, but the test does not detect newer variants of stale branding (e.g., other product names that might be introduced and later renamed).
- Files: `tests/test_repository.py:47`
- Risk: Low.
- Priority: Low.

**SKILL.md frontmatter test does not check `version`, `author`, `license`, `required_environment_variables`, or `required_credential_files`:**
- What's not tested: `tests/test_repository.py:30-35` asserts `name: revenium`, `metadata:`, `hermes:`, and `category: devops`. Commit `43c52e4` added `author`, `license`, `required_environment_variables`, `required_credential_files` to the frontmatter as "spec-required" fields, but no test pins them.
- Files: `tests/test_repository.py:30-35`, `skills/revenium/SKILL.md:1-20`
- Risk: A future edit could drop a spec-required field and ship to the tap without anyone noticing.
- Priority: Medium.

**Halt message wording in SKILL.md not pinned:**
- What's not tested: The exact halt response string at `skills/revenium/SKILL.md:35` is described in CLAUDE.md as contractual but no test asserts its presence or shape.
- Files: `skills/revenium/SKILL.md:35`
- Risk: A copy-edit pass could subtly change wording in a way that drifts from what Hermes consumers expect.
- Priority: Medium.

---

*Concerns audit: 2026-05-12*
