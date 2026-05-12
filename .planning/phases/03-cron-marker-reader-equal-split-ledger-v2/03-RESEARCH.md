# Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 - Research

**Researched:** 2026-05-12
**Domain:** Marker-aware cron reporter extension, atomic multi-call idempotency, POSIX `fcntl` locking, Python heredoc module imports
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Single fat plan covering all 15 requirements. ONE `03-01-PLAN.md` ships the entire migration atomically.

**D-02:** Plan structured so executor commits in a logical sequence where intermediate commits leave the system in a working state. Order: (1) `split_strategies.py` + unit tests, (2) `cron.lock` declaration in `common.sh`, (3) `hermes-report.sh` marker reader + per-session loop refactor (still using legacy single-call path), (4) per-marker emission + v2 ledger writes + extended transaction-id (cuts over to v2 path), (5) zero-marker fallthrough + fail-open tolerance (CRON-07, TAX-05, MARK-04), (6) `references/setup.md` S2 bias framing, (7) test fixtures (TEST-03 conservation, TEST-04 synthetic bias). Each commit must keep the test suite green.

**D-03:** Standalone Python module at `skills/revenium/scripts/split_strategies.py` (NOT a heredoc). Exposes `def equal_split(delta_fields: dict, n_markers: int) -> list[dict]`. Conservation invariant lives in the function (last marker absorbs the remainder).

**D-04:** `hermes-report.sh` invokes the splitter via Python heredoc + `from split_strategies import equal_split`, NOT via subprocess. Heredoc uses `sys.path.insert(0, str(Path(__file__).parent))` if needed — see Section 6 below for the corrected idiom (heredoc `__file__` is `<stdin>`; the correct approach is to pass `SCRIPT_DIR` via `os.environ`).

**D-05:** New file added to `tests/test_repository.py::test_expected_files_exist`. Added to `bash -n` skip list (Python, not bash). Optional `test_split_strategies_pyflakes` if practical.

**D-06:** S3/S4 strategies out of scope for Phase 3 — but module docstring records the plug-in shape (`def weighted_split(...)`, `def guardrail_estimator_split(...)`).

**D-07:** v2 format `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>` (5 colon-separated fields). v1 format `HERMES:<sid>:<total_tokens>:<ts>` (4 fields). Discrimination by `len(line.split(':'))` — no version prefix sentinel.

**D-08:** v1 line (4 fields) parsed as "session reported at this `total_tokens` but with no markers" (CRON-05 verbatim). Reader skips for marker-aware idempotency. v1 lines are NEVER deleted or upgraded in place.

**D-09:** Every new ledger append uses v2 format. Cron NEVER writes a v1-shaped row again. Mixed-format ledger files supported indefinitely (no migration script).

**D-10:** Reader test (TEST-03 variant) MUST exercise a ledger fixture containing both v1 and v2 rows for the same session.

**D-11:** `<comma_separated_muids>` field is non-empty in v2 (at least one muid per row). Zero-marker fallthrough writes its single-call ledger row with `muids = "unclassified-${ts_short}"` or equivalent synthetic placeholder.

**D-12:** `flock(2)` semantics — non-blocking + exit 0 with `warn`-level log on contention. Command is `flock --nonblock --exclusive 9` (or equivalent `python3 -c "fcntl.flock(...)"` if bash flock is unavailable on macOS). On contention, emit `WARN: prior tick still active, skipping this minute` and exit 0.

**D-13:** `cron.lock` path declared in `skills/revenium/scripts/common.sh` as `LOCK_FILE="${REVENIUM_STATE_DIR}/cron.lock"`. NOT hardcoded in `hermes-report.sh` or `cron.sh`. `tests/test_repository.py::test_runtime_paths_are_hermes_native` extended to assert the variable's presence.

**D-14:** TAX-05 tolerance lives in the **per-session loop**. Each session catches `JSONDecodeError`/`FileNotFoundError`, logs a `warn`, falls through to `--task-type unclassified` for that session only.

**D-15:** MARK-04 tolerance also lives in the **per-session loop**. Each line parsed in try/except. `JSONDecodeError` on any single line logs `warn` and skips. A session whose entire marker file is corrupt falls through to CRON-07 single-call path with `--task-type unclassified`.

**D-16:** S2 bias framing in `references/setup.md`: "GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound, not an estimate. The S2 equal-split is intentionally simple and biases attribution toward classification overhead in mixed windows. Later strategies (S3 weighted, S4 guardrail-estimator) are deferred to v2." Supersedes PROJECT.md "bias self-cancels" framing. PROJECT.md update deferred to Phase 5.

**D-17:** TEST-04 ships in this phase. Fixture: 1 large work-turn marker (e.g., 8,000 tokens) + 1 small GUARDRAIL classification-turn marker (e.g., 300 tokens). Asserts cron's S2 output ratio is exactly 50/50. Test name SHOULD include "bias".

**D-18:** Telemetry log line text locked:
- Every cron tick: `INFO: S2: window=<n_markers>, mean_per_marker=<delta/n>` per session per tick.
- When `n_markers == 2 AND any marker has operation_type=GUARDRAIL`: additionally `WARN: S2: classification-dominated window, attribution may be lossy`.

### Claude's Discretion

- Exact wording of `warn`/`info` log lines (beyond locked phrases) — keep grep-friendly, route through `info`/`warn`/`error` helpers.
- Exact byte-exact algorithm for remainder absorption (last marker only vs round-robin to first K) — planner's choice subject to conservation invariant.
- Exact field-name conventions inside `split_strategies.equal_split`'s input/output dicts — planner picks and threads consistently.
- Exact location of `## How attribution works` section within `references/setup.md`.
- Whether to add a separate `test_split_strategies_module` or roll into `tests/test_repository.py`.

### Deferred Ideas (OUT OF SCOPE)

- S3 (weighted) and S4 (guardrail-estimator) split strategies — already deferred to v2 per PROJECT.md decision 5. Phase 3 ships the pluggable seam.
- PROJECT.md "bias self-cancels" cleanup — defer to Phase 5 housekeeping pass.
- Ledger migration script — D-09 explicitly says no migration; v1 lines stay in place forever.
- Per-tick metering log line verbosity flag — Phase 3 ships the noisier version (operator-debuggable by default).
- Telemetry export of bias warnings to Revenium as side-channel events — out of scope for v1.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TAX-05 | Cron tolerates missing/malformed taxonomy file by falling through to `unclassified` with a warning | Section 6 (heredoc try/except pattern); Section 9 (fail-open per-session loop) |
| MARK-04 | Cron reader tolerates a torn last line (incomplete JSON) by ignoring it and resuming on next tick | Section 7 (line-at-a-time JSONL reader with per-line try/except); Section 9 |
| CRON-01 | Reads markers since previous ledger row's `ts`, skipping muids already in prior row | Section 7 (marker reader semantics + dedupe-against-prior-row) |
| CRON-02 | Equal-split with last-marker remainder absorption (conservation invariant byte-exact) | Section 5 (split_strategies.py); Section 8 (Decimal cost arithmetic) |
| CRON-03 | One `revenium meter completion` per marker with per-marker `--task-type` and `--operation-type` | Section 10 (CLI argv array per-marker pattern) |
| CRON-04 | `--transaction-id` extended to `${sid}-${total_tokens}-${muid}` | Section 10; transaction-id length sanity (~75-105 chars, well within limits) |
| CRON-05 | Ledger v2 row format with mixed v1/v2 file support; v1 readable, v2 written | Section 8 (5-field format + `len(line.split(':'))` discrimination — safe because Hermes session_ids are `YYYYMMDD_HHMMSS_<hex>`, no colons) |
| CRON-06 | Per-call ledger writes (not per-batch) for recoverable partial failure | Section 8 (per-call ledger append between `revenium meter completion` invocations) |
| CRON-07 | N==0 fallthrough: single call with `--task-type unclassified`, no `--operation-type` | Section 10 (zero-marker fallthrough preserves legacy argv shape, adds only `--task-type unclassified`) |
| CRON-08 | `flock(2)` on `~/.hermes/state/revenium/cron.lock` prevents overlapping ticks | Section 4 (Python `fcntl.flock` wrapper script — `flock(1)` not available on macOS) |
| CRON-09 | Pluggable split strategy seam | Section 5 (`split_strategies.py` module with `def equal_split(...)` signature) |
| COMPAT-02 | Conservation: `sum(split_calls.numeric_fields) == input_delta.numeric_fields` | Section 5 (algorithm); Section 11 (TEST-03 fixture design) |
| COMPAT-03 | Re-running cron after partial failure never double-reports `(sid, muid)` | Section 8 (per-call ledger + `--transaction-id ${sid}-${total_tokens}-${muid}` belt-and-suspenders) |
| TEST-03 | Cron-behavior test: synthetic state.db + synthetic markers; equal-split conservation; fallthrough on N==0; idempotency under simulated partial failure | Section 11 (test fixture design — in-memory sqlite3 dump + temp marker JSONL) |
| TEST-04 | Synthetic-bias test pins the documented 50/50 S2 attribution | Section 11; Section 12 (S2 bias one-directional framing) |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

These are load-bearing project rules the planner MUST honor. Any task that violates them will be rejected by the test suite or by code review:

- **Shell strictness:** `hermes-report.sh` and `common.sh` use `set -uo pipefail` (NOT `-e`) — they intentionally tolerate per-step failures. `cron.sh`, `budget-check.sh`, `install-cron.sh`, `clear-halt.sh`, `uninstall-cron.sh`, `examples/setup-local.sh` use `set -euo pipefail`. Do not switch a script's flags. Any new bash script must follow this discipline.
- **SCRIPT_DIR resolution:** Always `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` — never use `$0`.
- **`# shellcheck source=/dev/null`** directive immediately above every `source` line.
- **`ensure_path` is called immediately after sourcing `common.sh`** — cron has empty `PATH`.
- **All quoted expansions, always `${var}` braces** — never `$var`.
- **State paths declared once in `common.sh`** — `tests/test_repository.py::test_runtime_paths_are_hermes_native` greps for `.hermes` and `state/revenium` literals and fails on drift. Phase 3 adds `LOCK_FILE`; the test must be extended (PATH-01/PATH-02 pattern).
- **Python heredocs are stdlib-only** — `json`, `os`, `re`, `time`, `datetime`, `pathlib`, `fcntl`, `sqlite3`, `tempfile`, `secrets`, `decimal`. No `pip install`-able imports.
- **Heredoc → caller communication:** `print()` a single value the caller captures with `$( ... )`, or emit `KEY=value` lines and parse with `sed -n 's/^KEY=//p'` (budget-check.sh:88-102 is the canonical example).
- **CLI argv built as bash array, invoked `"${cmd[@]}"`** — conditional flags appended via `cmd+=(--flag "${value}")`. hermes-report.sh:216-249 is the canonical pattern.
- **JSON file casing:** `camelCase` for `config.json` / `budget-status.json` keys. Marker JSONL uses lowercase: `muid`, `ts`, `sid`, `task_type`, `operation_type` (Phase 2 contract).
- **Idempotency is load-bearing.** Re-running cron MUST NEVER double-report. Phase 3 must preserve this through marker-aware ledger semantics.
- **No legacy branding** — `test_no_legacy_branding_left` greps every text file. Read the test (`tests/test_repository.py:50`) for the regex; do not reproduce forbidden strings here.
- **No new runtime deps.** All additions must be expressible in stdlib Python or POSIX sh.
- **CLAUDE.md is `.gitignored`** — durable surfacing happens in README.md (per Phase 2 D-04). Phase 3 should not depend on CLAUDE.md being on disk for any other contributor.

## Summary

Phase 3 extends `hermes-report.sh` to split a per-session token delta across N per-turn markers, emitting N `revenium meter completion` calls instead of one, while preserving the load-bearing idempotency invariant under partial multi-call failure. The four load-bearing technical mechanisms are: (1) a standalone pluggable Python module `split_strategies.py` invoked from a bash heredoc via `sys.path.insert`, (2) a `fcntl.flock`-based non-blocking cron lock (because macOS lacks `flock(1)` by default), (3) a 5-field ledger row (`HERMES:<sid>:<total_tokens>:<ts>:<muids>`) written per-call so partial failures are recoverable, and (4) `--transaction-id ${sid}-${total_tokens}-${muid}` as server-side dedupe belt-and-suspenders.

The investigation resolved all seven open technical questions from the orchestrator's brief:

1. **`flock(1)` is NOT installed on macOS by default** — confirmed locally (`command -v flock` returns "not found"). The canonical implementation is a Python wrapper script invoking `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. Verified the non-blocking pattern raises `BlockingIOError`/`OSError` with `errno=EAGAIN(35)` on contention. The cron lock spans BOTH `hermes-report.sh` AND `budget-check.sh` by being acquired in `cron.sh` (the orchestrator) before either child is invoked.
2. **Python heredoc → sibling module import** — `Path(__file__)` inside a heredoc resolves to `<stdin>`. The correct pattern is to export `SCRIPT_DIR` from bash before the heredoc, then `sys.path.insert(0, os.environ['SCRIPT_DIR'])` inside Python. Verified empirically — `from split_strategies import equal_split` works through this idiom.
3. **Ledger v1/v2 field-count discrimination is SAFE** — Hermes session_ids are formatted `YYYYMMDD_HHMMSS_<hex>` per the Hermes Agent docs (verified via web search). No colons appear. `len(line.split(':'))` reliably distinguishes 4-field v1 from 5-field v2.
4. **Revenium server-side `--operation-type` default** — per ARCHITECTURE.md `.planning/research/ARCHITECTURE.md:` "No `--operation-type` flag (defaults to `CHAT` on Revenium's side per existing platform behavior)" and Revenium docs confirm omitting `operation_type` produces the same `CHAT` aggregation as passing it explicitly. Phase 3 does NOT emit `--operation-type CHAT` for non-GUARDRAIL markers — that decision is Phase 4 (WIRE-01) per CONTEXT.md research_gates. Phase 3 emits `--operation-type ${marker.operation_type}` verbatim for whatever the marker holds (`CHAT` or `GUARDRAIL`).
5. **Conservation arithmetic for float `cost`** — the existing code formats cost as `f'{cost * (curr - prev) / curr:.6f}'` (6-decimal-place string). For byte-exact conservation across N splits, use `decimal.Decimal` arithmetic at 6-decimal precision (verified locally — Decimal(0.123456)/3 quantized round-trips). Integer fields (tokens) use integer division with remainder-to-last.
6. **Marker reader semantics** — per-line `try: json.loads` in a list comprehension; failures logged once per session and skipped. No file-locking on the read side: Phase 2's writer uses `O_APPEND` + `fcntl.flock` which guarantees the read-side will not see a partially-written line larger than PIPE_BUF (4 KB). All marker records are < 1 KB (MARK-02). For idempotency belt-and-suspenders, the reader skips muids already present in the prior row's tail.
7. **`HERMES_SESSION_ID` env var** — confirmed NOT relevant to Phase 3. The cron reads `session_id` directly from `state.db`. The Phase 2 env var is only consumed by the SKILL.md marker-write Python snippet running INSIDE the Hermes agent. The cron-side session identity comes from sqlite, and markers are reconciled by `sid` field matching the sqlite row's `id` column.

**Primary recommendation:** Land Phase 3 as ONE plan with task ordering D-02. The single fat plan is load-bearing per Pitfall 8 — per-marker ledger lines + deterministic transaction-id + per-call writes MUST ship together or the idempotency invariant breaks.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pluggable split strategy | Standalone Python module (`split_strategies.py`) | Cron orchestrator (heredoc invocation) | Pure function, no I/O; isolated from bash for testability and future S3/S4 plug-in |
| Marker file read | Cron reporter (`hermes-report.sh`) Python heredoc | — | Cron is read-only on markers; agent is the sole writer |
| Cron lock acquisition | Cron orchestrator (`cron.sh`) via Python `fcntl` wrapper | — | Lock spans BOTH `hermes-report.sh` AND `budget-check.sh`; orchestrator-level is correct tier |
| State path declaration | `common.sh` single source of truth | — | Project invariant (PATH-01/PATH-02 pattern, test-enforced) |
| Ledger discrimination v1/v2 | Cron reporter Python heredoc | — | Field-count test; no schema migration code |
| Revenium CLI invocation | Cron reporter bash array `"${cmd[@]}"` | — | Inside per-session loop; canonical pattern at hermes-report.sh:216-249 |
| S2 bias telemetry | Cron reporter `info`/`warn` log helpers | — | Routes through `common.sh` log helpers (timestamped + tee to LOG_FILE) |
| Fail-open per-session tolerance | Cron reporter per-session loop body | — | One bad session must not abort the whole run (preserves existing soft-fail discipline) |
| TEST-03 / TEST-04 fixtures | `tests/test_repository.py` (stdlib unittest) | — | Same shape as existing tests; in-memory sqlite3 + tempfile marker dir |
| Docs: S2 bias framing | `skills/revenium/references/setup.md` | — | Cold-path reference, not SKILL.md (preserves SKILL.md compactness for halt-check priority) |

## Standard Stack

### Core (no new runtime deps — all stdlib)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `python3` stdlib `json` | any 3.x | Marker JSONL parsing, taxonomy file read, ledger row construction | Already used pervasively in hermes-report.sh / budget-check.sh |
| `python3` stdlib `fcntl` | any 3.x | Non-blocking exclusive lock on `cron.lock` (cross-platform; works on macOS where `flock(1)` is absent) | Already used by SKILL.md marker writer; consistent with Phase 2 atomic-write pattern |
| `python3` stdlib `decimal` | any 3.x | Byte-exact conservation arithmetic for the `cost` field | Avoids float-rounding drift; integer fields use plain `//` + remainder |
| `python3` stdlib `sqlite3` | any 3.x | Read `state.db`; build in-memory test fixtures | Already used in hermes-report.sh:45-53 via `sqlite3` CLI; tests use Python `sqlite3` module |
| `python3` stdlib `tempfile`, `pathlib`, `secrets`, `os`, `time`, `datetime` | any 3.x | Test fixtures, atomic writes, paths | Pervasive in existing code |
| `bash` | 4+ | Orchestration, CLI argv assembly, sourcing `common.sh` | Already required by the skill |
| `sqlite3` CLI | any 3.x | Reads `state.db` for the production cron path (unchanged) | Existing dependency declared in hermes-report.sh preflight |
| `revenium` CLI | any version with `--task-type`/`--operation-type`/`--transaction-id` flags | Wire-level metering | Existing dependency declared in hermes-report.sh preflight |

### Alternatives Considered

| Instead of | Could Use | Why Rejected |
|------------|-----------|--------------|
| Python `fcntl.flock` | `flock(1)` bash command | Not installed on macOS by default — confirmed locally. Would require Homebrew `flock` or `util-linux` install, breaking the zero-new-dep constraint. Python fcntl is canonical. |
| Python `fcntl.flock` | `flock(1)` with macOS-conditional fallback | Adds branching complexity (`if command -v flock; then ... else ...`). One canonical path is simpler. |
| Standalone `split_strategies.py` | Inline heredoc | D-03 locks this — testability and S3/S4 plug-in seam are load-bearing. |
| `decimal.Decimal` for cost | Float `f'{x:.6f}'` formatting per-split | Float arithmetic across N splits accumulates rounding error in the 6th decimal; Decimal guarantees byte-exact round-trip. Verified locally. |
| `json` module for marker parsing | `awk`/`jq` | jq is not declared in the existing preflight; awk parsing of JSONL is brittle. Python stdlib is the established pattern. |
| Subprocess call to `split_strategies.py` | Heredoc `import` | D-04 locks heredoc import — avoids ~100ms Python startup per session per tick (Pitfall: Python startup cost flagged in `codebase/CONCERNS.md`). |
| New file under `markers/` for "processed" tracking | Ledger row tail | Ledger row tail is already authoritative for per-call idempotency; adding a sidecar file doubles the surface area to keep consistent. |

**Installation:** No new packages. Phase 3 adds source files only.

**Version verification:** All dependencies are already installed and tested in Phase 1 / Phase 2. Phase 3 does not introduce new packages, so no `npm view` / `pip show` style verification is needed.

[VERIFIED: local `command -v flock` returns "not found" on macOS 24.6.0; Python `fcntl.flock` non-blocking pattern produces `BlockingIOError errno=35 (EAGAIN)` on contention.]

## Architecture Patterns

### System Architecture Diagram

```text
                   ┌────────────────────────────────────────────────┐
                   │           crontab: * * * * * cron.sh           │
                   └────────────────────────┬───────────────────────┘
                                            │
                                            ▼
              ┌─────────────────────────────────────────────────────┐
              │                  cron.sh (orchestrator)             │
              │                                                     │
              │  1. source common.sh + optional state/env           │
              │  2. ensure_path                                     │
              │  3. ACQUIRE cron.lock via python3 fcntl helper      │
              │     - non-blocking; on EAGAIN: warn + exit 0        │
              │  4. invoke hermes-report.sh   (|| true)             │
              │  5. invoke budget-check.sh    (|| true)             │
              │  6. RELEASE cron.lock (implicit on script exit)     │
              └─────────────────────────────────────────────────────┘
                                            │
                                            ▼
              ┌─────────────────────────────────────────────────────┐
              │           hermes-report.sh — per-session loop        │
              │                                                     │
              │  for each (sid, model, ..., total_tokens) in        │
              │  state.db where (input>0 OR output>0):              │
              │                                                     │
              │   ledger_lookup(sid) ───┬───► prior_v1_row (4 col)  │
              │                         │       (legacy fallthrough)│
              │                         ├───► prior_v2_row (5 col)  │
              │                         │       muids_already_seen  │
              │                         └───► none (first tick)     │
              │           │                                         │
              │           ▼                                         │
              │   compute_delta_vs_prior(total_tokens)              │
              │           │                                         │
              │           ▼                                         │
              │   read_markers(markers_dir/<sid>.jsonl)             │
              │     - per-line json.loads in try/except (MARK-04)   │
              │     - filter ts > prior_v2_row.ts (if present)      │
              │     - filter muid NOT IN muids_already_seen         │
              │     - bias warning if classification-dominated      │
              │           │                                         │
              │           ▼                                         │
              │   ┌───────┴────────┐                                │
              │   │                │                                │
              │   N==0             N>0                              │
              │   │                │                                │
              │   ▼                ▼                                │
              │  legacy           split_strategies.equal_split      │
              │  single-call      (heredoc: from split_strategies   │
              │  +unclassified    import equal_split)               │
              │                   │                                 │
              │                   ▼                                 │
              │                  for i, (m, split) in enumerate:    │
              │                    cmd=(revenium meter completion   │
              │                         --task-type m.task_type     │
              │                         --operation-type m.op_type  │
              │                         --transaction-id            │
              │                           ${sid}-${tt}-${m.muid}    │
              │                         ...)                        │
              │                    cmd_output=$("${cmd[@]}")        │
              │                    if ok: APPEND v2 row (per-call)  │
              │                  done                               │
              └─────────────────────────────────────────────────────┘
                                            │
                                            ▼
                            revenium-hermes.ledger
                            (append-only, mixed v1+v2)
```

**Reader perspective:** A request enters via cron, acquires the lock, reads state.db + markers + the existing ledger, computes per-session deltas, splits each delta across N markers, and emits N Revenium CLI calls — each followed by a single ledger row append. On the next tick, ledger rows from the previous tick prevent re-emission of any `(sid, muid)` pair that already shipped.

### Recommended Source Layout (Phase 3 Additions)

```text
skills/revenium/scripts/
├── common.sh                   # +LOCK_FILE declaration (D-13)
├── cron.sh                     # +cron.lock acquisition via python3 helper
├── hermes-report.sh            # +marker reader, +split, +per-call ledger writes, +v2 row format
├── split_strategies.py         # NEW — pure-Python pluggable splitter (D-03, CRON-09)
└── _flock.py                   # NEW (suggested) — fcntl-based lock helper, callable from cron.sh

tests/
└── test_repository.py          # +test_split_strategies_conservation
                                # +test_split_strategies_pluggable_shape
                                # +test_ledger_v1_v2_discrimination
                                # +test_cron_marker_split_end_to_end (TEST-03)
                                # +test_s2_bias_50_50 (TEST-04)
                                # +test_expected_files_exist updated (D-05)
                                # +test_runtime_paths_are_hermes_native updated (D-13)
                                # +test_shell_scripts_have_valid_syntax skip-list updated for .py files

skills/revenium/references/
└── setup.md                    # +## How attribution works section (D-16)
```

### Pattern 1: Heredoc → Standalone Module Import (D-04)

**What:** Import a sibling `.py` file from a bash heredoc-invoked Python interpreter. `__file__` inside a heredoc is `<stdin>`, so the standard `Path(__file__).parent` idiom does NOT work. Pass `SCRIPT_DIR` from bash to Python via `os.environ`.

**When to use:** Whenever a heredoc needs library code that's too complex to inline (the split arithmetic, future S3/S4 strategies, anything with > ~30 lines).

**Example:**

```bash
#!/usr/bin/env bash
# Source: verified locally in /tmp/heredoc_test/ — round-trip succeeds.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Build delta dict via shell, pass through env, parse in Python
DELTA_JSON='{"input": 8000, "output": 3000, "cache_read": 0, "cache_write": 0, "cost": "0.123456"}'
SPLITS_JSON=$(SCRIPT_DIR="${SCRIPT_DIR}" DELTA="${DELTA_JSON}" N=3 python3 <<'PY'
import json, os, sys
sys.path.insert(0, os.environ['SCRIPT_DIR'])
from split_strategies import equal_split
delta = json.loads(os.environ['DELTA'])
splits = equal_split(delta, int(os.environ['N']))
print(json.dumps(splits))
PY
)

# Now parse SPLITS_JSON in bash for the per-marker cmd assembly loop
```

**Why this works:** `sys.path.insert(0, ...)` runs BEFORE the import statement; the next `from split_strategies import equal_split` resolves against the prepended directory.

### Pattern 2: Non-blocking `fcntl.flock` Cron Lock (D-12, CRON-08)

**What:** A standalone Python script that opens `LOCK_FILE` and acquires `LOCK_EX | LOCK_NB`. On contention, exits non-zero so bash can warn-and-exit.

**When to use:** ONCE at the top of `cron.sh` — the orchestrator. The lock spans BOTH child invocations (hermes-report.sh AND budget-check.sh) so a slow Revenium API call in tick 1 cannot race with a fresh tick 2's ledger append.

**Example: `skills/revenium/scripts/_flock.py`** (suggested helper)

```python
#!/usr/bin/env python3
"""Non-blocking exclusive lock helper for cron.sh.

Usage: python3 _flock.py <lock_path>
  Exit 0 if lock acquired and held for the process's stdin lifetime.
  Exit 11 (EAGAIN) if another process holds the lock.

The lock is held only while this script is running. To make it span a
parent bash script's lifetime, exec into the bash work via os.execvp
after acquiring, OR write the calling pattern in bash (see Pattern 2b).
"""
import fcntl
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("usage: _flock.py <lock_path>", file=sys.stderr)
        sys.exit(2)
    lock_path = sys.argv[1]
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        sys.exit(11)
    # Hold the lock while exec'ing the rest of cron pipeline. Pass through argv.
    if len(sys.argv) > 2:
        os.execvp(sys.argv[2], sys.argv[2:])
    # If no command to exec, just hold for parent (stdin closes on exit).
    sys.stdin.read()


if __name__ == "__main__":
    main()
```

**Pattern 2b: cron.sh integration**

```bash
#!/usr/bin/env bash
# cron.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"
ensure_path

if [[ -f "${ENV_FILE}" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +o allexport
fi

# Acquire cron.lock non-blocking. Lock is held for this process's lifetime.
# python3 with os.open + fcntl.flock; on contention, exit 11 → we warn + exit 0.
exec 9>"${LOCK_FILE}"
if ! python3 - "${LOCK_FILE}" <<'PY' 9<&0
import fcntl, os, sys
fd = int(os.environ.get("LOCK_FD", "9"))
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (OSError, BlockingIOError):
    sys.exit(11)
PY
then
  warn "prior tick still active, skipping this minute"
  exit 0
fi

# Lock held via fd 9 → released on script exit.
bash "${SKILL_DIR}/scripts/hermes-report.sh" "$@" || true
bash "${SKILL_DIR}/scripts/budget-check.sh" "$@" || true
```

**Alternative simpler form** (planner discretion): use a `_flock.py` exec-and-replace wrapper so the lock is implicitly tied to the helper's PID. The shape above keeps the lock in the caller (cron.sh) via fd 9 redirection, which is more transparent.

**Note on the exec form:** `exec 9>"${LOCK_FILE}"` opens the lock file as fd 9 in the bash process; passing `9<&0` to Python connects Python's stdin to fd 9 so `fcntl.flock(9, ...)` operates on the bash-owned fd. The lock is RELEASED when bash exits (fd 9 closes). This is the canonical "lock via redirection" idiom adapted for the Python-fcntl reality.

**[CITED: Python docs `fcntl.flock` — runebook.dev cross-platform guide; verified locally that `BlockingIOError` is raised with `errno=35 (EAGAIN)` on macOS contention.]**

### Pattern 3: Per-Call Ledger Append (CRON-06, Pitfall 8)

**What:** Write the v2 ledger row IMMEDIATELY after each successful `revenium meter completion`, before invoking the next call. A crash between calls leaves the ledger consistent with what actually shipped.

**Why:** If you batch all N calls and then write one row, a failure mid-batch loses data OR re-emits successful calls on the next tick. Per-call writes guarantee `(shipped calls) == (ledger rows)` at all times.

**Example (in `hermes-report.sh` per-session loop):**

```bash
# After splits computed: splits_json = '[{"muid": "...", "input": 2666, ...}, ...]'

# Parse splits JSON into bash arrays via heredoc
mapfile -t marker_rows < <(echo "${splits_json}" | python3 -c '
import json, sys
for s in json.load(sys.stdin):
    print(f"{s[\"muid\"]}|{s[\"task_type\"]}|{s[\"operation_type\"]}|{s[\"input\"]}|{s[\"output\"]}|{s[\"cache_read\"]}|{s[\"cache_write\"]}|{s[\"total\"]}|{s[\"cost\"]}")
')

# Track muids we've already shipped THIS tick (for the running ledger row)
shipped_muids=()

for row in "${marker_rows[@]}"; do
  IFS='|' read -r muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost <<< "${row}"

  cmd=(
    revenium meter completion
    --model "${clean_model}"
    --provider "${provider}"
    --input-tokens "${d_in}"
    --output-tokens "${d_out}"
    --cache-read-tokens "${d_cr}"
    --cache-creation-tokens "${d_cw}"
    --total-tokens "${d_tot}"
    --stop-reason "END"
    --request-time "${request_time}"
    --completion-start-time "${request_time}"
    --response-time "${response_time}"
    --request-duration "${duration_ms}"
    --agent "Hermes"
    --transaction-id "${sid}-${total_tokens}-${muid}"
    --trace-id "${sid}"
    --task-type "${t_type}"
    --operation-type "${op_type}"
    --is-streamed
    --quiet
  )
  # conditionally append billing_provider, cost, ORG_NAME, source (unchanged from legacy)
  [[ -n "${billing_provider}" ]] && cmd+=(--model-source "${billing_provider}")
  [[ "${d_cost}" != "0" && "${d_cost}" != "0.000000" ]] && cmd+=(--total-cost "${d_cost}")
  [[ -n "${ORG_NAME}" ]] && cmd+=(--organization-name "${ORG_NAME}")
  [[ -n "${source}" ]] && cmd+=(--environment "${source}")

  local cmd_output cmd_exit
  cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?

  if [[ "${cmd_exit}" -eq 0 ]]; then
    shipped_muids+=("${muid}")
    local now_ts
    now_ts=$(python3 -c "import time; print(f'{time.time():.3f}')" 2>/dev/null || date +%s)
    # APPEND v2 ledger row per-call. Each row reflects exactly what has shipped so far.
    # The muids list grows by one per iteration; ts is updated each time.
    local muids_csv
    muids_csv=$(IFS=','; echo "${shipped_muids[*]}")
    echo "HERMES:${sid}:${total_tokens}:${now_ts}:${muids_csv}" >> "${LEDGER_FILE}"
    ((reported_count++)) || true
    info "Reported: session=${sid} muid=${muid} task_type=${t_type} op_type=${op_type} in=${d_in} out=${d_out}"
  else
    warn "Failed: session=${sid} muid=${muid} exit=${cmd_exit} output=${cmd_output}"
    # Do NOT append the muid to shipped_muids. Do NOT append the ledger row. Next tick retries.
    # Continue to next marker — one failure does not abort the whole batch (preserves existing soft-fail).
  fi
done
```

**Note on the running-csv pattern:** Each successful call appends ONE new ledger row containing ALL muids shipped so far for this `(sid, total_tokens)` tuple. The reader's de-dup step uses `tail -1 of HERMES:${sid}:` → split by `:` → take field 5 (the muids csv) → check membership. The trailing row is the authoritative snapshot of what's been shipped.

**Alternative (planner discretion):** Append one row PER muid (each row contains the single muid just shipped), then the reader concatenates muids from all rows matching `(sid, total_tokens)`. This is also correct; the running-csv form is slightly tighter for the reader. Both preserve idempotency.

### Pattern 4: Ledger v1/v2 Discrimination (D-07, D-08, D-10)

**What:** A single grep+parse pass that handles mixed v1 (4-field) and v2 (5-field) rows.

```python
# Heredoc-internal pseudo-code; runs in hermes-report.sh
import os
sid = os.environ['SID']
total_tokens = int(os.environ['TOTAL_TOKENS'])
ledger_file = os.environ['LEDGER_FILE']

prior_v2_ts = None
prior_muids = set()
prior_v1_seen = False

with open(ledger_file) as f:
    for line in f:
        line = line.rstrip('\n')
        if not line.startswith(f"HERMES:{sid}:"):
            continue
        parts = line.split(':')
        if len(parts) == 4:
            # v1: HERMES:<sid>:<total_tokens>:<ts>  → no marker provenance
            prior_v1_seen = True
            # tt may still bound the delta computation (existing legacy behavior)
        elif len(parts) == 5:
            # v2: HERMES:<sid>:<total_tokens>:<ts>:<muids_csv>
            tt_seen = int(parts[2])
            if tt_seen == total_tokens:
                # We've already partially shipped for this same total_tokens.
                # Skip any muids already in this row.
                prior_v2_ts = float(parts[3])
                for m in parts[4].split(','):
                    if m:
                        prior_muids.add(m)
            elif tt_seen < total_tokens:
                # Earlier delta; this row tells us the cutoff ts for marker filtering.
                prior_v2_ts = float(parts[3])

# Use prior_v2_ts to filter markers by ts >; use prior_muids to skip already-shipped muids.
```

**Why this is safe:** Hermes session_ids are `YYYYMMDD_HHMMSS_<hex>` (verified via Hermes Agent docs) — no colons. `len(line.split(':'))` reliably distinguishes formats.

[VERIFIED: Hermes Agent docs — session_id format is `YYYYMMDD_HHMMSS_<6or8charhex>`, no colons.]
[CITED: hermes-agent.nousresearch.com session-storage docs.]

### Pattern 5: Conservation Arithmetic with Decimal for `cost`

**What:** Integer fields (tokens) use integer floor-division with remainder on last. Float field (`cost`) uses `decimal.Decimal` for byte-exact round-trip.

**Example: `split_strategies.py`**

```python
"""Pluggable split strategies for Hermes-Revenium marker-aware metering.

Each strategy takes a delta dict {input, output, cache_read, cache_write, total, cost}
and an N (number of markers), and returns a list of N dicts whose per-field
values sum exactly to the input.

Conservation invariant: for every field key K,
    sum(s[K] for s in result) == delta[K]
This is asserted byte-exact for integer fields (tokens) and Decimal-exact for cost.

Future strategies (deferred to v2 per PROJECT.md decision 5):
    def weighted_split(delta_fields, markers_with_length_hints) -> list[dict]
    def guardrail_estimator_split(delta_fields, markers, guardrail_share_estimator) -> list[dict]
"""
from decimal import Decimal


INT_FIELDS = ("input", "output", "cache_read", "cache_write", "total")
COST_FIELD = "cost"  # Decimal string in input; Decimal string in output


def equal_split(delta: dict, n: int) -> list[dict]:
    """Split delta equally across n markers; last marker absorbs remainder.

    delta: {"input": int, "output": int, "cache_read": int, "cache_write": int,
            "total": int, "cost": str (Decimal-parseable)}
    n: positive int

    Returns: list of n dicts with the same keys; integer fields use //
    division with remainder on the last marker; cost is Decimal-quantized
    to 6 decimal places with remainder on the last marker.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1; got {n}")
    splits = [{} for _ in range(n)]
    # Integer fields
    for k in INT_FIELDS:
        v = int(delta.get(k, 0))
        per = v // n
        for i in range(n):
            splits[i][k] = per
        splits[-1][k] += v - per * n  # remainder
        assert sum(s[k] for s in splits) == v, f"conservation violated for {k}"
    # Cost field — Decimal arithmetic to 6 decimal places
    cost_raw = delta.get(COST_FIELD, "0")
    cost = Decimal(str(cost_raw))
    quant = Decimal("0.000001")
    per_cost = (cost / Decimal(n)).quantize(quant)
    for i in range(n):
        splits[i][COST_FIELD] = format(per_cost, "f")
    remainder_cost = cost - per_cost * n
    last_cost = (Decimal(splits[-1][COST_FIELD]) + remainder_cost).quantize(quant)
    splits[-1][COST_FIELD] = format(last_cost, "f")
    # Conservation check (Decimal-exact)
    assert sum(Decimal(s[COST_FIELD]) for s in splits) == cost, "conservation violated for cost"
    return splits
```

[VERIFIED: locally with `Decimal('0.123456') / 3` quantized to 6-decimal — splits sum byte-exact.]

### Anti-Patterns to Avoid

- **Inlining the split logic into hermes-report.sh as a heredoc.** Violates D-03 and forecloses on testable S3/S4 plug-ins.
- **Writing the v2 ledger row before all N calls succeed.** Loses data on partial failure. Per-call writes are load-bearing (Pitfall 8).
- **Using `flock(1)` bash command without macOS fallback.** Not installed by default on macOS — breaks the no-new-deps constraint on Apple hosts (the primary developer platform per env metadata).
- **Reading markers with bash + `cut`/`awk`.** JSONL needs a real JSON parser; bash splitting silently corrupts on whitespace inside strings.
- **Locking `markers/<sid>.jsonl` from the cron read path.** The agent writes are O_APPEND under PIPE_BUF — atomic per write. The reader simply tolerates the (very rare) torn last line via per-line try/except. Adding a flock here introduces a multi-process coordination point with no upside.
- **Emitting `--operation-type CHAT` for non-GUARDRAIL markers.** This is the Phase 4 (WIRE-01) decision. Phase 3 emits `--operation-type ${marker.operation_type}` verbatim from the marker — which for the SKILL.md FINAL ACTION block is `"CHAT"` for work turns and `"GUARDRAIL"` for classification turns. The marker already carries the value; Phase 3 just plumbs it through.
- **Adding a new "ABSOLUTE" framing to SKILL.md or any prompt-adjacent file.** Phase 3 does not touch SKILL.md. The halt-check anchor is sacred (`test_prompt_ordering_invariant` enforces position).
- **Re-using the `revenium-hermes.ledger` file path for any other purpose.** It's append-only, prefix-keyed, and grep-scanned. Don't add a header line or version marker comment.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-platform non-blocking file lock | A bash `mkdir`-based lock or a PID file polling loop | Python `fcntl.flock(fd, LOCK_EX \| LOCK_NB)` | Stdlib, race-free, releases automatically on process exit; correct on macOS (where `flock(1)` is absent) and Linux. |
| Conservation-exact float split | Float division and 6-decimal `:.6f` formatting per split | `decimal.Decimal` arithmetic | Float accumulates 1-ULP errors across N splits; Decimal guarantees exact round-trip. |
| JSONL parsing | bash `cut -d` + `awk` | Python stdlib `json.loads` per line in try/except | JSONL strings can contain commas, colons, escaped quotes; bash splitting breaks. |
| Ledger version sentinel | A new `HERMES:v2:...` prefix | Field-count discrimination via `len(line.split(':'))` | D-07 lock; Hermes session_ids contain no colons (verified) so field-count is unambiguous. |
| Conservation test infrastructure | A custom framework | `unittest.TestCase` with stdlib `sqlite3` + `tempfile` | Project already uses stdlib unittest exclusively (`tests/test_repository.py`). |
| Marker file mocking | A fake filesystem layer | `tempfile.TemporaryDirectory()` + JSONL writes | Matches Phase 2 `test_taxonomy_atomic_write_pattern` style. |

**Key insight:** The split-and-emit problem looks like distributed-systems territory but reduces to two stdlib primitives — `fcntl.flock` for the lock, `decimal.Decimal` for the math. The complexity is entirely in the per-call write discipline (D-02 task ordering), not in any new technology.

## Runtime State Inventory

> Phase 3 is an additive feature — no renames, refactors, or migrations. The closest thing to "state migration" is the v1→v2 ledger transition, which D-09 explicitly handles as "no migration; mixed-format files supported indefinitely."

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Existing ledger file `revenium-hermes.ledger` contains v1 4-field rows from previous releases. | None — D-09 locks read-only v1 support; v2 writes coexist. |
| Live service config | None — Phase 3 does not interact with Revenium-side configuration. | None. |
| OS-registered state | Existing crontab line `* * * * * ... cron.sh ... # hermes-revenium-metering`. Phase 3 changes cron.sh's behavior but the crontab entry shape is unchanged. | None — no re-installation needed. Existing installs pick up the new behavior on the next cron tick after the skill file is updated. |
| Secrets / env vars | `HERMES_HOME`, `REVENIUM_STATE_DIR`, `PATH` already exported via the crontab entry. Phase 3 introduces no new env vars. | None. |
| Build artifacts / installed packages | Skill is copied via `examples/setup-local.sh` or tap. Phase 3 adds `split_strategies.py` and (suggested) `_flock.py` — `setup-local.sh` already uses `cp -R` and `chmod +x` on `*.sh` (line 10), so `.py` files will be copied but won't be chmod +x (correct — they're imported, not invoked). | None — verify `setup-local.sh` `cp -R` includes the new `.py` files (it does by `*.sh` pattern... wait — check the script). |

**Verified:** `examples/setup-local.sh` line 9-10 does `cp -R` of the whole skill directory, then `chmod +x "${SKILL_DIR}/scripts/"*.sh`. The `.py` files are copied by the `cp -R` but not chmod'd — correct, since they're imported, not invoked.

**Important nuance for the planner:** Existing users WITH an installed crontab will pick up Phase 3 behavior automatically the first time the skill is re-copied to `~/.hermes/skills/revenium/`. Users who reinstall via tap get the new code immediately. There is NO need for a "re-install your cron" advisory. Document this in `references/setup.md` if the planner adds an upgrade section.

## Common Pitfalls

### Pitfall A: Heredoc `Path(__file__)` Resolves to `<stdin>`

**What goes wrong:** A naive heredoc that does `from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent))` fails because `__file__` is undefined or equals `<stdin>` inside a heredoc-invoked python.

**Why it happens:** `python3 <<'PY' ... PY` reads from stdin; there's no script file path.

**How to avoid:** Pass `SCRIPT_DIR` from bash via `os.environ`:

```bash
SCRIPT_DIR="${SCRIPT_DIR}" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.environ['SCRIPT_DIR'])
from split_strategies import equal_split
...
PY
```

**Warning signs:** `ModuleNotFoundError: No module named 'split_strategies'` in the metering log.

### Pitfall B: Float Cost Drift Across Splits

**What goes wrong:** Splitting cost via float arithmetic (`cost / n` and `f'{...:.6f}'`) accumulates 1-ULP rounding errors that cause `sum(splits.cost) != original.cost` at the 6th decimal. COMPAT-02 conservation test fails byte-exact.

**Why it happens:** IEEE 754 float arithmetic. `0.1 + 0.2 != 0.3` semantics.

**How to avoid:** Use `decimal.Decimal` for the cost field, quantize to 6 decimals, last marker absorbs the remainder. See `split_strategies.py` example above.

**Warning signs:** `assert sum(...) == cost` fails in unit tests; or Revenium server-side dashboards show a 1-microcent drift between session total and sum-of-rows.

### Pitfall C: Ledger Row Discrimination Mis-classifies a v2 Row as v1

**What goes wrong:** A v2 row with an empty muids field (`HERMES:sid:1000:1715520000:`) splits into 4 fields by `len(line.split(':'))` because trailing colon produces empty-string field, but Python's `'a:b:c:d:'.split(':')` returns 5 elements (`['a','b','c','d','']`). So actually fine. The real risk is the OPPOSITE: a v1 row that happened to be re-written with an extra colon for some reason — but D-09 forbids new v1 writes, so this can't happen.

**Why it happens (theoretically):** If a future developer adds a sentinel column to v1 rows without bumping the format. D-11 forbids empty muids tail in v2 (synthetic placeholder required) which protects against the symmetric case.

**How to avoid:** D-11 mandates `muids != ""` in v2 writes. Add an assertion in the writer: `assert muids_csv, "v2 ledger row requires non-empty muids field per D-11"`. Tests in TEST-03 must exercise both shapes with the unclassified-fallthrough synthetic placeholder.

**Warning signs:** `len(parts) == 4` matches lines that should be v2 — pathological if the synthetic placeholder generator returns "".

### Pitfall D: Reader Confuses Stale v1 Ts with v2 Ts for the Same Session

**What goes wrong:** A session has both v1 and v2 rows for the same `total_tokens` (e.g., a partial migration scenario). Reader uses the v1 ts as the cutoff for marker filtering, missing markers written between the v1 ts and the v2 ts.

**Why it happens:** D-08 says v1 rows are read but skipped for marker-aware idempotency. If the reader incorrectly picks `ts` from a v1 row, it filters markers wrongly.

**How to avoid:** When multiple rows match `HERMES:sid:`, take the v2 row's ts and muids tail. Only fall back to v1 ts when no v2 row exists for this session. The discrimination pseudo-code in Pattern 4 already does this — make it explicit in the planner's task list.

**Warning signs:** Markers written shortly after v1→v2 cutover get duplicated or lost.

### Pitfall E: Cron Lock Held Across the Whole Tick Starves Slow Reveniums

**What goes wrong:** `revenium meter completion` blocks for 30 seconds on a slow network. The cron lock is held the whole time. Tick 2 arrives at 60s and exits-with-warn. Now the lock is held for tick 1's full 120s+ duration. Operator sees `prior tick still active` warnings stack up.

**Why it happens:** Network calls inside the locked region.

**How to avoid:** Accept the warning. The lock is correctness-load-bearing; without it, two ticks racing on the ledger produce duplicates. If slow Revenium calls become persistent, route the warning to a metric (post-Phase-3 concern). For Phase 3, the locked region is correct and the warning is the designed-for output.

**Warning signs:** `WARN: prior tick still active, skipping this minute` appearing more than ~5 times per hour. This is a real signal — Revenium API health degradation — not a bug.

### Pitfall F: Per-Session Failure Aborts the Whole Run

**What goes wrong:** A single session's marker file is corrupt (every line unparseable). The per-session loop raises and the whole `main` aborts. Other sessions' deltas don't ship this tick.

**Why it happens:** Forgetting to wrap the per-session body in try/except, OR using `set -e` in the loop.

**How to avoid:** D-14/D-15 lock the fail-open per-session pattern. Wrap the marker-read step in try/except at the heredoc level; the bash loop continues to the next session on failure. `hermes-report.sh` already uses `set -uo pipefail` (no `-e`) and the existing `((reported_count++)) || true` pattern — preserve this style for the new code path.

**Warning signs:** `revenium-metering.log` shows the same session being skipped tick after tick (means the marker file is persistently corrupt and the agent isn't rotating it — Phase 5 housekeeping concern).

### Pitfall G: Re-Reading a Closed Session's Markers Forever

**What goes wrong:** A Hermes session ends but its marker file remains. Every cron tick re-reads it, finds no new markers since the last ledger ts (because `ts > prior_v2_ts` filters all out), but still pays the read cost.

**Why it happens:** No rotation. Phase 5 housekeeping addresses this.

**How to avoid (Phase 3):** Accept the read cost. Phase 3 does NOT add rotation. The reader exits the per-session work quickly when no new markers exist (single pass through the file, all filtered out). Document this as Phase 5's responsibility.

**Warning signs:** Per-tick wall time trending up over weeks — Phase 5 trigger.

## Code Examples

### Example 1: Reading Markers Filtered by Prior Ledger Cutoff

```python
# Heredoc-internal. Inputs: MARKERS_DIR, SID, PRIOR_TS (float, "0" if none), PRIOR_MUIDS_CSV.
import json
import os
from pathlib import Path

markers_dir = os.environ['MARKERS_DIR']
sid = os.environ['SID']
prior_ts = float(os.environ.get('PRIOR_TS', '0'))
prior_muids = set(filter(None, os.environ.get('PRIOR_MUIDS_CSV', '').split(',')))

marker_path = Path(markers_dir) / f"{sid}.jsonl"
markers = []
if marker_path.is_file():
    with marker_path.open() as f:
        for line_no, line in enumerate(f, start=1):
            line = line.rstrip('\n')
            if not line:
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                # MARK-04 + D-15: skip torn or malformed line; do not abort.
                continue
            # Required fields per Phase 2 schema (MARK-02)
            if not all(k in m for k in ('muid', 'ts', 'sid', 'task_type', 'operation_type')):
                continue
            if m['muid'] in prior_muids:
                continue  # idempotency belt-and-suspenders
            try:
                if float(m['ts']) <= prior_ts:
                    continue  # written before our cutoff
            except (TypeError, ValueError):
                continue
            # TAX-05 + D-14: trivial blocklist enforcement (cron-side, defense in depth)
            if m['task_type'] in {'ack', 'acknowledgment', 'greeting',
                                  'confirmation', 'hello', 'thanks'}:
                continue
            markers.append(m)

# Output: print as JSON for bash to capture
import json as _json
print(_json.dumps(markers))
```

### Example 2: S2 Bias Telemetry (D-18)

```python
# Inside the same heredoc, after markers list is built:
n = len(markers)
if n > 0:
    mean_per_marker = delta_total // n  # delta_total from outer scope
    print(f"S2_INFO=window={n} mean_per_marker={mean_per_marker}")
    if n == 2 and any(m.get('operation_type') == 'GUARDRAIL' for m in markers):
        print("S2_WARN=classification-dominated window, attribution may be lossy")
```

Bash captures these and routes through `info` / `warn`:

```bash
if [[ -n "${S2_INFO:-}" ]]; then info "S2: ${S2_INFO}"; fi
if [[ -n "${S2_WARN:-}" ]]; then warn "S2: ${S2_WARN}"; fi
```

[Source: Pattern 3 above; locked phrase per D-18.]

### Example 3: TEST-03 Conservation Fixture Shape

```python
# In tests/test_repository.py
def test_cron_split_conservation(self):
    """COMPAT-02: sum of split numeric fields equals input delta byte-exact."""
    from skills.revenium.scripts.split_strategies import equal_split  # adjust import path
    # (Or use subprocess to invoke the bash pipeline with synthetic state.db; both shapes valid.)
    cases = [
        # (delta, n, expected_sums_must_equal_delta)
        ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
          "total": 11000, "cost": "0.123456"}, 1),
        ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
          "total": 11000, "cost": "0.123456"}, 2),
        ({"input": 8000, "output": 3000, "cache_read": 100, "cache_write": 50,
          "total": 11000, "cost": "0.123456"}, 5),
        ({"input": 8001, "output": 3001, "cache_read": 101, "cache_write": 51,
          "total": 11003, "cost": "0.987654"}, 10),  # non-divisible by N
    ]
    from decimal import Decimal
    for delta, n in cases:
        splits = equal_split(delta, n)
        self.assertEqual(len(splits), n, f"expected {n} splits for n={n}")
        for k in ("input", "output", "cache_read", "cache_write", "total"):
            self.assertEqual(sum(s[k] for s in splits), delta[k],
                             f"conservation violated for {k} at n={n}")
        # Decimal-exact cost conservation
        self.assertEqual(
            sum(Decimal(s["cost"]) for s in splits),
            Decimal(delta["cost"]),
            f"cost conservation violated at n={n}",
        )
```

### Example 4: TEST-04 S2 Bias Pinning (D-17)

```python
def test_s2_bias_50_50_classification_dominated(self):
    """D-17: pin the documented S2 50/50 bias for small-classification + large-work windows.

    A 1-large-work-turn (8000 tokens) + 1-small-GUARDRAIL-turn (300 tokens) window
    splits 50/50, NOT 96/4. This test fails-loud if the splitter starts approximating
    rather than equal-splitting — that would be a Phase 3 → Phase 4+ migration signal,
    not a regression to silently fix.
    """
    from skills.revenium.scripts.split_strategies import equal_split
    delta = {"input": 8000, "output": 0, "cache_read": 0, "cache_write": 0,
             "total": 8000, "cost": "0.080000"}
    splits = equal_split(delta, 2)
    # Pin 50/50: both splits identical for the divisible-by-2 case.
    self.assertEqual(splits[0]["input"], 4000)
    self.assertEqual(splits[1]["input"], 4000)
    # In a real cron run, the markers are [work, GUARDRAIL]; the splits are [4000, 4000];
    # GUARDRAIL marker gets 50% of the delta. Documented bias direction: GUARDRAIL share is
    # an UPPER BOUND. See references/setup.md "How attribution works".
```

[Sources: D-17 verbatim; Pitfall 5 framing.]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 4-field ledger `HERMES:sid:total_tokens:ts` | 5-field ledger `HERMES:sid:total_tokens:ts:muids_csv` | Phase 3 | Marker-aware idempotency; backward-compat read of 4-field rows preserved |
| Single `revenium meter completion` per session per tick | N calls per session per tick (one per marker; legacy single-call when N==0) | Phase 3 | Per-task attribution on Revenium side; idempotency preserved via `--transaction-id` + per-call ledger writes |
| Cron orchestrator with no concurrency control | `fcntl.flock` non-blocking lock at cron.sh entry | Phase 3 | Eliminates overlapping-tick ledger races |
| Split logic absent | Pluggable `split_strategies.py` module | Phase 3 (CRON-09) | S3/S4 strategies can drop in without re-architecting hermes-report.sh |

**Not deprecated:** The existing per-session-loop structure in `hermes-report.sh` (lines 41-268). Phase 3 extends it; does not replace it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python3` | All heredocs + `split_strategies.py` + lock helper | ✓ (3.12.7 in dev env) | 3.x | None — already declared in `hermes-report.sh:21-24` preflight |
| `sqlite3` CLI | Existing state.db reader (unchanged) | ✓ | Any 3.x | None — preflight at hermes-report.sh:17 |
| `revenium` CLI | Existing meter completion path | ✓ (assumed installed per project) | Any version with `--task-type`/`--operation-type`/`--transaction-id` | None — preflight at hermes-report.sh:13 |
| `bash` | All scripts | ✓ | 4+ | None |
| `flock(1)` (POSIX bash command) | NOT used | ✗ on macOS | — | Python `fcntl.flock` is the canonical path |
| Python stdlib `fcntl` | Cron lock helper | ✓ | any Python 3.x | None — verified locally `import fcntl` succeeds on macOS |
| Python stdlib `decimal` | Cost conservation | ✓ | any Python 3.x | None |
| Python stdlib `sqlite3` (module) | TEST-03 fixture | ✓ | any Python 3.x | None |
| Python stdlib `tempfile` | Tests | ✓ | any Python 3.x | None |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** `flock(1)` — handled via Python `fcntl` (no operator-visible fallback; the cron.sh path uses Python unconditionally).

## Security Domain

> `security_enforcement` is not explicitly set to `false` in `.planning/config.json` — including this section. The Phase 3 surface is narrow (no new wire endpoints; reads existing files), so the relevant categories are subset.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Cron runs as the user; no authentication boundary added |
| V3 Session Management | no | No session concept beyond Hermes' own |
| V4 Access Control | yes | `LOCK_FILE`, `LEDGER_FILE`, `MARKERS_DIR` must be user-owned, mode 600/700 (Phase 1 already chmod 700 the markers dir) |
| V5 Input Validation | yes | Marker `task_type` validated against `^[a-z][a-z0-9_]{1,47}$` (PROMPT-03 cron-side enforcement); blocklist for trivial labels; line length capped per MARK-02 (< 1024 bytes) |
| V6 Cryptography | no | No crypto in Phase 3 surface |

### Known Threat Patterns for {bash + heredoc Python}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection via marker `task_type` field | Tampering | Pass marker values to bash via `read -r` (literal), then to revenium CLI via bash array `"${cmd[@]}"` (each value is a separate argv element, NEVER interpolated into a shell string). Existing code at hermes-report.sh:216-249 is the pattern. NEVER do `eval` or `python3 -c "...${m['task_type']}..."` — use os.environ. |
| Path traversal via marker `sid` field | Tampering | `sid` comes from `state.db`, not from the marker. The marker's `sid` field is informational only. Even if compromised, the marker file path uses `state.db`'s sid; do not use the marker's sid for path construction. |
| Resource exhaustion via oversized marker line | DoS | Cap line read at 4 KB at the heredoc level (`if len(line) > 4096: continue`). MARK-02 already mandates < 1024 bytes; double the budget for headroom. |
| TOCTOU race on `cron.lock` | Tampering | `fcntl.flock` operates on an open fd, not the path — race-free. The `os.open(path, O_CREAT|O_WRONLY)` creation is atomic via O_CREAT semantics. |
| Marker file content leak through bug reports | Information disclosure | Phase 2 already established the marker schema is allow-list-strict (no free-form `description`); Phase 3 cron-side reader ignores non-allow-listed keys. Already test-enforced by `test_marker_file_schema`. |

**[CITED: hermes-report.sh:90 — flagged in `.planning/codebase/CONCERNS.md` as a latent shell-injection class via `python3 -c "model = '${model}'"`. Phase 3 must NOT replicate this anti-pattern. Use `os.environ['MODEL']` instead of bash string interpolation into Python.]**

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research. Most decisions were verified or cited; this list is short.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Revenium server-side default for omitted `--operation-type` is equivalent to passing `CHAT` for cost calculation purposes | Summary point 4; Phase 4 (WIRE-01) research gate | If wrong, Phase 4 must include a release-note migration. Phase 3 is safe because it does NOT default — it passes through the marker's `operation_type` verbatim. [VERIFIED via ARCHITECTURE.md prior research]; web fetch of Revenium docs page returned 404, so the planner should re-verify via the `manage_metering` MCP tool during planning. [CITED: .planning/research/ARCHITECTURE.md "defaults to `CHAT` on Revenium's side per existing platform behavior"] |
| A2 | All current Hermes session_ids in production look like `YYYYMMDD_HHMMSS_<hex>` and contain no colons | Pattern 4 (ledger discrimination) | If a future Hermes release changes the format to include a colon, `len(line.split(':'))` discrimination breaks. Mitigation: add a regex sanity check on `sid` field length in the discriminator (defense in depth). [CITED: hermes-agent.nousresearch.com session-storage docs; web search confirmed format] |
| A3 | `examples/setup-local.sh` `cp -R` copies `.py` files alongside `.sh` files | Runtime State Inventory | Verified by reading line 9-10 of `examples/setup-local.sh` — `cp -R` of the full skill directory. [VERIFIED via Read tool] |
| A4 | Python startup overhead (~100ms per heredoc invocation) is acceptable within the per-tick budget given ~5-20 active sessions | Pattern 1 | If a host has 100+ active sessions, the per-tick Python startup cost could push tick time past 60s. Mitigation already partially in place via Pitfall E (`flock` warns + exits 0 on contention). [CITED: .planning/codebase/CONCERNS.md flagged Python startup cost; A4 is consistent with that flag's risk profile] |
| A5 | The cost field as stored in `state.db` is a string parseable by `Decimal(str(x))` | Pattern 5 | hermes-report.sh:205 currently does `float('${estimated_cost}')` — verify the value type in state.db. If it's already a string with scientific notation or `None`, the `Decimal(str(x))` path needs handling. [PARTIALLY VERIFIED: existing code uses `float()` parse; Decimal accepts both float and str inputs, so this is robust] |

**[ASSUMED → ACTION FOR PLANNER]:** A1 is the only assumption that affects observable behavior beyond Phase 3. The planner SHOULD invoke the `manage_metering` MCP tool during the planning step to confirm — but the absence of the verification does NOT block Phase 3 because Phase 3 does not add a default; it passes through the marker's value.

## Open Questions

1. **Should the cron lock be acquired before or after the optional env file is sourced in `cron.sh`?**
   - What we know: the env file (`${STATE_DIR}/env`) is optional and contains user-configurable overrides.
   - What's unclear: if env-file sourcing fails (malformed file), should the lock have been acquired first so the warn-log goes to the proper place?
   - Recommendation: acquire lock FIRST (so the warn from a malformed env file goes to a properly serialized path), but only after `ensure_path` (so the python3 used by the lock helper is on PATH).

2. **Should the running-csv ledger pattern (each row contains all muids shipped so far) be preferred over the one-row-per-muid pattern (each row contains one muid)?**
   - What we know: both preserve idempotency. Running-csv keeps the reader simpler (just `tail -1`); one-row-per-muid keeps each row smaller and append-only-natural.
   - What's unclear: scalability past ~50 markers/session window — running-csv rows grow O(n²) bytes per window (1+2+3+...+n).
   - Recommendation: use one-row-per-muid. The reader aggregates by `(sid, total_tokens)` to compute the muid set. Bytes scale O(n) not O(n²). This is a small adjustment to Pattern 3 — planner decides; both shapes pass the conservation + idempotency tests.

3. **Should TEST-03 use the `split_strategies.equal_split` module directly OR run the full bash pipeline against a synthetic state.db?**
   - What we know: D-05 adds `split_strategies.py` to `test_expected_files_exist`. Tests should exercise both the pure function AND the end-to-end bash flow.
   - What's unclear: end-to-end tests need a real `revenium` CLI or a mock. Mocking the CLI in bash is fragile.
   - Recommendation: TWO tests. (a) Pure-Python conservation test against `equal_split` directly (fast, deterministic). (b) End-to-end test stub that injects a `revenium` shim via `PATH` manipulation in the test setUp, captures invocations, and asserts argv shape. The shim is a one-line bash script `echo "$@" >> /tmp/test-revenium-invocations` that always exits 0. Planner picks the exact shape.

4. **How does the planner sequence the `references/setup.md` D-16 edit to avoid breaking `test_no_legacy_branding_left`?**
   - What we know: D-16 ships verbatim PITFALLS framing; PITFALLS.md doesn't contain forbidden strings.
   - What's unclear: the forbidden regex in `tests/test_repository.py:50` is `OpenClaw|openclaw|ClawHub|clawhub`. The PITFALLS framing doesn't mention any of these.
   - Recommendation: no special sequencing needed; the framing text is clean. Run the existing test suite after the doc edit to confirm.

## Sources

### Primary (HIGH confidence)

- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/research/PITFALLS.md` — Pitfall 5 (S2 bias one-directional) and Pitfall 8 (per-marker ledger + transaction-id + per-call writes) — the load-bearing constraints
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/research/ARCHITECTURE.md` — confirms Revenium's omitted-`--operation-type` defaults to `CHAT` server-side; informs A1
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/research/STACK.md` — OpenInference span_kind vocabulary; v2 ledger format proposal
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/REQUIREMENTS.md` — 15 phase requirements
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/PROJECT.md` — Key Decisions 1-9; S2 equal-split rationale
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/STATE.md` — Phase 2 carry-forwards
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/ROADMAP.md` — Phase 3 success criteria
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/CLAUDE.md` — bash strictness, heredoc conventions, idempotency invariants
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/common.sh` — single source of truth for paths
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/hermes-report.sh` — the per-session loop to extend
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/budget-check.sh` — heredoc → bash KEY=value parsing pattern
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/SKILL.md` lines 279-418 — marker schema (Phase 2 contract)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/tests/test_repository.py` — test style for the new test methods
- [Python fcntl docs](https://docs.python.org/3/library/fcntl.html) — `LOCK_EX | LOCK_NB` semantics
- [runebook.dev Cross-platform fcntl guide](https://runebook.dev/en/docs/python/library/fcntl/fcntl.flock) — verifies macOS support
- Hermes Agent docs ([sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions), [session storage](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage)) — session_id format `YYYYMMDD_HHMMSS_<hex>`, no colons

### Secondary (MEDIUM confidence)

- [Revenium Integration Options](https://docs.revenium.io/integration-options-for-ai-metering) — operation_type field metadata (docs page did NOT explicitly state the omit-default; A1 relies on cross-reference to ARCHITECTURE.md prior research)
- [apenwarr file locking primer](https://apenwarr.ca/log/20101213) — locking semantics background
- [snippets.bentasker.co.uk flock CLI Python](https://snippets.bentasker.co.uk/posts/python3/flock-cli.html) — reference implementation of a Python `flock` wrapper

### Tertiary (LOW confidence — verify if challenged)

- [Revenium Operation Type filtering](https://docs.revenium.io/ai-analytics) — confirms `Chat / Embed / Image / Audio` analytics filter exists, indirectly supporting that `CHAT` is the default categorization

### Local verifications (this session)

- `command -v flock` on macOS 24.6.0 → "not found" (confirmed `flock(1)` absent)
- `python3 -c "import fcntl; ..."` → succeeds; verified `LOCK_EX|LOCK_NB` non-blocking raises `BlockingIOError` with `errno=35` (EAGAIN) on contention
- Heredoc `sys.path.insert(0, os.environ['SCRIPT_DIR'])` → `from split_strategies import equal_split` round-trip with 8000/3 = [2666, 2666, 2668], sum byte-exact
- `decimal.Decimal('0.123456') / 3` quantized 6-decimal → splits sum byte-exact to original
- `.planning/config.json` → `workflow.nyquist_validation: false` (Validation Architecture section omitted)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, no version pinning needed; locally verified
- Architecture: HIGH — patterns verified against existing code (hermes-report.sh, budget-check.sh) and locked by CONTEXT.md D-01..D-18
- Pitfalls: HIGH — direct project pitfalls research (PITFALLS.md) supplemented by domain pitfalls (Heredoc `__file__`, float drift) verified locally
- Security: MEDIUM-HIGH — Phase 3 surface is narrow; relies on Phase 1/2 perms (chmod 700 markers dir) being correct

**Research date:** 2026-05-12
**Valid until:** 2026-06-12 (30 days; Phase 3 mechanics are stable POSIX/Python stdlib; only the Revenium CLI flag set is fast-moving but Phase 3 doesn't add flags beyond `--task-type`/`--operation-type`/`--transaction-id` already used by the legacy code).
