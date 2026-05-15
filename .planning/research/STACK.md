# Stack Research

**Domain:** v1.1 "Agentic Job Tracking" — adding Revenium agentic-job lifecycle (`jobs create` / `--task-id` / `jobs outcome`) to the existing `revenium` Hermes skill
**Researched:** 2026-05-14
**Confidence:** HIGH — all CLI flags verified against `revenium schema` and `--help` on the authenticated CLI on this host; `--dry-run` exercised against the live `/v2/api/jobs` surface.

> This supersedes the v1.0 STACK.md (task-classification milestone). The v1.0
> stack — Bash + stdlib Python 3 + sqlite3 + `revenium` CLI + cron, paths in
> `scripts/common.sh` — is unchanged. This document only covers the v1.1
> agentic-job additions.

## Bottom Line

**No new tools are needed.** The entire v1.1 feature is expressible with the
stack already in the repo: `bash` + Python 3 stdlib heredocs + `sqlite3` + the
`revenium` CLI. The `revenium jobs` subcommand tree and the `--task-id` flag on
`revenium meter completion` are both present in the CLI installed on this host
(`/opt/homebrew/bin/revenium`) and were verified directly. There is **no SDK,
no HTTP client, and no `curl` fallback** — the CLI is the complete and only
transport. The no-new-runtime-dependency constraint holds with zero deviation.

The only "stack change" is a CLI **version floor**: installs must have a
`revenium` build new enough to expose `jobs` and `meter completion --task-id`.
The user just patched the CLI to add `--task-id`; this must be encoded as a
preflight capability probe (see Version Compatibility below), not assumed.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `revenium` CLI | A build exposing `jobs` + `meter completion --task-id` (verified present on `/opt/homebrew/bin/revenium`, 2026-05-14) | Job lifecycle transport: `jobs create`, `jobs outcome`, and `--task-id` on `meter completion` | It is the *only* sanctioned wire path. v1.0 already shells out to `revenium meter completion`; v1.1 adds two more subcommands of the same binary. No new dependency, no new auth surface, no new error model. |
| `bash` 4+ (`set -uo pipefail`) | GNU bash 5.2 on this host; must stay bash 3.2-safe per the `clear-halt.sh` carry-forward item | Orchestrates the new job-create / `--task-id` stamping / outcome calls inside `hermes-report.sh` | Same shell the cron pipeline already runs. New logic is array-built CLI invocations (the `cmd=( ... )` pattern at `hermes-report.sh:556-577`), not a new language. |
| Python 3 stdlib (heredocs) | `python3` already required by `hermes-report.sh:21-24`; stdlib only (`json`, `os`, `sys`, `time`, `fcntl`, `pathlib`) | Parse job markers from JSONL, group markers by `agenticJobId`, serialize/round-trip values across the bash boundary | Identical pattern to the v1.0 `split_strategies.py` marker reader at `hermes-report.sh:334-446`. `fcntl` (stdlib) covers the mint-back-race hardening item — no new package. |
| `sqlite3` CLI | Already required (`hermes-report.sh:17-20`) | Read-only session query against `~/.hermes/state.db` | Unchanged from v1.0. Jobs add nothing here — job identity comes from marker files, not the DB. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `json` (stdlib) | builtin | Parse the extended job-marker JSONL; build the `--metadata` JSON string for `jobs outcome` | Every cron tick that finds job markers. Already imported in the v1.0 marker reader. |
| Python `fcntl` (stdlib) | builtin | `flock` around `_persist_label_to_taxonomy`'s temp-file write (v1.0 carry-forward hardening) and around any new job-state file the cron writes | Concurrency-sensitive writes only. POSIX-only — acceptable, the skill declares `platforms: [macos, linux]`. |
| Python `time` / `pathlib` / `os` / `sys` (stdlib) | builtin | Timestamps, marker-file paths, env passthrough | Already used throughout `hermes-report.sh` heredocs. No change. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `revenium schema` | Machine-readable CLI command tree (JSON: `commands` / `global_flags` / `exit_codes`) | Source of truth for flag verification. **Caveat:** the schema dump on this host lists the `jobs *` subcommands fully but is **stale for `meter completion`** — `meter completion` is absent from `meter`'s subcommand list even though `revenium meter completion --help` shows the full flag set including `--task-id`. Verify `meter completion` flags via `--help`, not `schema`. |
| `revenium <cmd> --dry-run` | Preview a `jobs create` / `jobs outcome` call without mutating server state — prints `Path:` and `Body:` | Use in tests and during phase development to confirm request shape. Verified: `jobs create --dry-run` → `POST /v2/api/jobs`, `Body: map[agenticJobId:... name:... type:...]`; `jobs outcome --dry-run` → `POST /v2/api/jobs/<id>/outcome`, `Body: map[executionStatus:SUCCESS]`. |
| Python `unittest` (stdlib) | Existing `tests/test_repository.py` invariant suite | New job-marker shape / idempotency tests extend this; no new test framework. |
| `bash -n` | Syntax check, run from inside the Python test suite | Unchanged. |

## Verified CLI Surface

All of the following were confirmed on the authenticated CLI on this host
(2026-05-14). Required markers and types are quoted from `revenium schema` /
`--help` verbatim.

### `revenium jobs create` — verified

```
revenium jobs create --agentic-job-id <ID> [--name <str>] [--type <str>] [--environment <str>] [--version <str>]
```

| Flag | Type | Required | Notes |
|------|------|----------|-------|
| `--agentic-job-id` | string | **REQUIRED** | "User-supplied external identifier". This is the `agenticJobId` the agent mints. |
| `--name` | string | no | "Human-readable job name" |
| `--type` | string | no | "Job category (e.g. loan-processing)" |
| `--environment` | string | no | "Deployment environment". Maps cleanly from `state.db.sessions.source` (already passed to `meter completion --environment`). |
| `--version` | string | no | "Job version identifier" |

`--dry-run` confirms: `POST /v2/api/jobs`, `Body: map[agenticJobId:... name:... type:...]`. Exit `0` on success.

### `revenium jobs outcome` — verified

```
revenium jobs outcome <agenticJobId> --result SUCCESS|FAILED|CANCELLED \
  [--outcome-type <str>] [--outcome-value <float64>] [--outcome-currency <ISO4217>] \
  [--metadata <json-string>] [--reported-by <str>]
```

| Flag / Arg | Type | Required | Notes |
|------------|------|----------|-------|
| `<agenticJobId>` | positional arg | **REQUIRED** | Positional, not a flag. |
| `--result` | string | **REQUIRED** | "Execution result: SUCCESS, FAILED, or CANCELLED". |
| `--outcome-type` | string | no | "Business outcome type" (e.g. `CONVERTED`). |
| `--outcome-value` | float64 | no | "Monetary value of the outcome". |
| `--outcome-currency` | string | no | "Currency code (ISO 4217), defaults to USD". |
| `--metadata` | string | no | "Additional metadata as JSON string" — build with Python `json.dumps` in a heredoc. |
| `--reported-by` | string | no | "Identifier of who reported the outcome". |

Description literally reads **"Report a job outcome (immutable)"** — confirms the
one-shot invariant. `--dry-run` confirms: `POST /v2/api/jobs/<id>/outcome`,
`Body: map[executionStatus:SUCCESS]` (note: `--result SUCCESS` serializes to
`executionStatus` in the request body).

### `revenium meter completion --task-id` — verified

`--task-id` is present (help text verbatim): *"Task identifier — correlates the
completion with an agentic job (use the same value as agenticJobId)."* It slots
into the existing `cmd=( revenium meter completion ... )` array in
`hermes-report.sh` exactly like the v1.0 `--task-type` / `--operation-type`
flags. Stamp it conditionally (`cmd+=(--task-id "${agentic_job_id}")`) only when
the marker carries a job id, so marker-less / job-less sessions stay
byte-identical to v1.0.

> **Schema caveat:** `meter completion` is missing from the `meter` subcommand
> list in `revenium schema` output (the schema lists `meter api-request`,
> `api-response`, `audio`, `event`, `image`, `tool-event`, `video` — but not
> `completion`). So `--task-id` could not be confirmed *from the schema*. It
> **was** confirmed from `revenium meter completion --help`, which lists all 36
> flags including `--task-id`. Treat `--help` as authoritative for `meter
> completion`; treat `schema` as authoritative for `jobs *`.

### Idempotency probes — verified

The v1.1 idempotency invariant ("re-running cron must never double-create a job
or double-report an outcome") is satisfiable with CLI calls alone:

- `revenium jobs get <agenticJobId> --output json` returns **process exit `3`**
  (`not_found`, confirmed with the raw `$?` and no pipeline masking) plus a JSON
  body `{"error":"Resource not found.","exit_code":3,"status":404}` when the job
  does not exist. This is a viable "does this job already exist?" probe.
- **Recommended primary mechanism:** extend the existing append-only ledger / add
  a sibling job-state file under `~/.hermes/state/revenium/` (path declared in
  `common.sh`). A local marker that says "job X already created" / "outcome for
  job X already reported" is cheaper and more reliable than a network probe, and
  mirrors the v1.0 ledger pattern (`HERMES:<sid>:<total>:<ts>:<muid>`). Use
  `jobs get` only as a belt-and-braces cross-check.
- Verified `revenium` exit codes (from `schema.exit_codes`): `ok=0`,
  `general=1`, `auth=2`, `not_found=3`, `validation=4`, `network=5`. Branch
  cron retry/skip logic on these.

## Integration Points (for the roadmapper / phase planners)

| File | Change | Notes |
|------|--------|-------|
| `skills/revenium/scripts/common.sh` | Add any new state-file path(s) here — e.g. a job-state / job-ledger file under `${STATE_DIR}`. **Declare nowhere else.** | `test_runtime_paths_are_hermes_native` enforces this. Follow the `${VAR:-default}` env-override shape used at lines 17-22. |
| `skills/revenium/scripts/hermes-report.sh` | (1) New preflight capability probe for `jobs` + `--task-id` (lines 13-32 area). (2) In the per-marker emission loop (`:553-610`), read `agenticJobId` from the extended marker and `cmd+=(--task-id "${agentic_job_id}")`. (3) New idempotent `jobs create` call before stamping the first completion for a job. (4) New `jobs outcome` call once per terminated arc. | The `cmd=( ... )` array idiom at `:556-577` is the template for the new `jobs` invocations too. Keep the zero-marker / job-less fallthrough (`:611-675`) byte-identical for backward compat. |
| Job-marker JSONL contract | Extend the v1.0 marker schema with optional job fields (`agenticJobId`, job `name`/`type`, outcome `result` + optional `outcome-*`). | Marker reader at `hermes-report.sh:340-446` already does per-line `json.loads` with `REQUIRED_KEYS` filtering — extend that key set / optional-key handling there. Per-line 4 KB cap and torn-line tolerance already exist. |
| `skills/revenium/SKILL.md` | FINAL ACTION marker block gains job-mint instructions (mint `agenticJobId`, declare job `name`/`type` + outcome at arc end). | Stack-neutral (prompt text), but it is the producer of the marker fields the cron consumes. |

## Installation

No installs. The v1.1 stack is a strict subset of what is already on a working
v1.0 host:

```bash
# Nothing to install. Required tooling already present and preflight-checked
# by hermes-report.sh:13-32:
#   - revenium  (CLI — must expose `jobs` + `meter completion --task-id`)
#   - sqlite3
#   - python3   (stdlib only — json, os, sys, time, fcntl, pathlib)
#   - bash

# The ONLY new preflight: confirm the CLI is new enough (see Version
# Compatibility). Suggested capability probe, exit-0-and-warn on miss
# (matches the existing fail-open preflight idiom at hermes-report.sh:13-32):
revenium jobs --help >/dev/null 2>&1 \
  || { warn "revenium CLI lacks 'jobs' — skipping job tracking"; }
revenium meter completion --help 2>&1 | grep -q -- '--task-id' \
  || { warn "revenium CLI lacks 'meter completion --task-id' — skipping job tracking"; }
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `revenium` CLI for all job calls | Direct HTTP to `/v2/api/jobs` (via `curl` or a Python stdlib `urllib.request` heredoc) | **Never, for v1.1.** Only if a needed operation were CLI-unreachable — it is not. `urllib.request` is stdlib so it would *technically* honor the no-new-dependency rule, but it duplicates the CLI's auth/retry/error model and is a clear deviation from the repo's "CLI is the transport" architecture. Reject. |
| Local job-state file for idempotency | `revenium jobs get` network probe on every tick | Use the network probe only as a secondary cross-check. A local file is faster, works offline, and matches the v1.0 ledger precedent. |
| `--metadata` built via Python `json.dumps` heredoc | `jq -n` to build the JSON string | `jq` is *not* a declared dependency of this repo (it happens to be on this host via Anaconda, but `hermes-report.sh` never preflights it). Building JSON in the already-required `python3` keeps the dependency set unchanged. Do not introduce `jq`. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `requests` / `httpx` / any pip HTTP client | Hard violation of the no-new-runtime-dependency constraint; the repo has deliberately never had an HTTP client. | `revenium` CLI subcommands. |
| `curl` for job calls | Not a declared/preflighted dependency; bypasses the CLI's auth and error model; flagged as a deviation in the milestone brief. | `revenium jobs create` / `revenium jobs outcome`. |
| `jq` for building/parsing job JSON | Not preflighted by `hermes-report.sh`; its presence on this host is incidental (Anaconda). Relying on it would add an undeclared dependency. | Python 3 stdlib `json` in a heredoc — the established pattern. |
| `revenium schema` as the source of truth for `meter completion` flags | The schema dump on this host omits the `meter completion` subcommand entirely (stale). Trusting it would make you think `--task-id` does not exist. | `revenium meter completion --help` for `meter completion`; `revenium schema` for the `jobs *` tree. |
| A Revenium SDK / language binding | None is in use; introducing one is a new dependency and a new failure surface. | The CLI is feature-complete for v1.1. |
| Assuming `--task-id` / `jobs` exist on every install | The user *just patched* the CLI to add `--task-id`. Older installs will not have it. Silent failure would break metering. | A preflight capability probe that fails open (exit 0 + `warn`), matching `hermes-report.sh:13-32`. |
| Branching cron logic on `$?` of a piped `revenium` call | A pipeline (e.g. `revenium jobs get ... | head`) masks the real process exit with the last pipe stage's exit. Observed: `jobs get <missing>` returned `0` through `| head` but `3` raw. | Capture exit without a pipe: `revenium jobs get ... >tmp 2>&1; rc=$?`. |

## Stack Patterns by Variant

**If the host's `revenium` CLI is too old (no `jobs` subcommand or no `--task-id`):**
- Skip all job-tracking logic; continue v1.0 metering unchanged.
- Emit a `warn` via the `common.sh` logger and `exit 0` — never abort the cron
  pipeline. This is the established fail-open preflight idiom.

**If a session's markers carry no `agenticJobId` (older skill, job-less arc):**
- Do not call `jobs create`, do not pass `--task-id`. The `meter completion`
  call is byte-identical to v1.0 (`--task-type` / `--operation-type` only).
- This is the backward-compatibility guarantee — verifiable by diffing the
  emitted `cmd` array against the v1.0 zero-marker fallthrough at `:620-641`.

**If the same job spans multiple cron ticks:**
- `jobs create` must be guarded by a local "already created" record so the
  second tick does not re-create. `jobs outcome` must be guarded the same way
  (it is server-side immutable — a double call is a hard error, not a no-op).
- Reuse the append-only-ledger discipline from v1.0; the idempotency key is the
  `agenticJobId`.

## Version Compatibility

| Component | Requirement | Notes |
|-----------|-------------|-------|
| `revenium` CLI | Must expose `revenium jobs *` **and** `revenium meter completion --task-id`. The CLI has **no `--version` flag** (`revenium --version` errors with "unknown flag: --version"). | Detect by capability, not by version string: `revenium jobs --help` and `grep -- --task-id` on `revenium meter completion --help`. Both confirmed present on `/opt/homebrew/bin/revenium` on this host 2026-05-14. The user's recent `--task-id` patch means a meaningful population of installs will lack it — the probe is mandatory. |
| `bash` | 3.2+ (must run on stock macOS bash 3.2). | The v1.1 hardening backlog includes a `clear-halt.sh` bash-3.2 fix (`${VAR@Q}` is bash 4.4+). New job code must avoid bash-4-only syntax for the same reason. |
| Python 3 | No minimum pinned; stdlib only. `fcntl` is POSIX-only — fine, skill targets macOS/Linux only. | Same as v1.0. |
| `sqlite3` | Any 3.x. | Unchanged; jobs add no DB usage. |
| `revenium schema` JSON shape | Keys: `commands` / `global_flags` / `exit_codes`. Each command node: `path` / `description` / `subcommands` / `flags` (each flag: `name`/`type`/`required`/`default`/`usage`). | Useful for tests, but **not reliable for `meter completion`** (stale — that subcommand is absent). Pin tests for that one command to `--help` output. |

## Sources

- `revenium schema` (live, authenticated CLI on this host, 2026-05-14) — verified the full `jobs` subcommand tree (`create`, `outcome`, `get`, `list`, `transactions`, `types`, `update`, `delete`, `roi`, `conversion-funnel`), all `jobs` flags/types/required-markers, plus `global_flags` and `exit_codes`. HIGH.
- `revenium jobs create --help`, `revenium jobs outcome --help` (live CLI, 2026-05-14) — cross-checked flag names, required markers, positional `<agenticJobId>` arg, and usage examples. HIGH.
- `revenium meter completion --help` (live CLI, 2026-05-14) — confirmed `--task-id` exists with the exact "correlates the completion with an agentic job" usage text; captured the full 36-flag set. Flagged: `meter completion` is absent from the `schema` dump. HIGH.
- `revenium jobs create --dry-run`, `revenium jobs outcome --dry-run`, `revenium jobs get <missing>` (live CLI, 2026-05-14) — confirmed request shapes (`POST /v2/api/jobs`, `POST /v2/api/jobs/<id>/outcome`, body field `executionStatus`), the `(immutable)` outcome semantics, and `not_found` → raw process exit `3`. HIGH.
- `skills/revenium/scripts/common.sh`, `skills/revenium/scripts/hermes-report.sh` (repo, read directly) — confirmed integration points, the `cmd=( ... )` array idiom, the fail-open preflight pattern, and the no-HTTP-client status quo. HIGH.
- `.planning/PROJECT.md` (repo) — v1.1 milestone scope, constraints, Key Decisions (`--task-id` is the wire link, outcomes one-shot). HIGH.

---
*Stack research for: v1.1 agentic-job tracking on the `revenium` Hermes skill*
*Researched: 2026-05-14*
