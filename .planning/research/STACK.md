# Stack Research

**Domain:** Agent-driven task classification + agent ↔ cron file-based contracts on top of an existing Bash/Python/sqlite3 metering skill
**Researched:** 2026-05-12
**Confidence:** HIGH for format/atomicity guidance, HIGH for OpenInference alignment, MEDIUM for OpenTelemetry GenAI alignment (still "Development" status)

This is a milestone extension to `hermes-revenium`. The existing stack (Bash + stdlib Python 3 + sqlite3 + `revenium` CLI + cron, paths declared in `scripts/common.sh`) is **not changing**. This document only covers what we add for marker writing, taxonomy maintenance, and cron-side marker consumption.

## TL;DR

| Question | Answer | Confidence |
|----------|--------|------------|
| Agent-driven classification approach | Skill-prompt instruction + agent-managed JSON taxonomy file; lookup-first protocol embedded in `SKILL.md`. No SDK, no decorator framework. | HIGH |
| Agent ↔ cron contract format | Per-session append-only JSONL under `~/.hermes/state/revenium/markers/<session_id>.jsonl`. One record per substantive turn, one `\n`-terminated UTF-8 line. | HIGH |
| Atomicity on POSIX | Records must be `< 4096 bytes` and written with a single `O_APPEND` write. On Linux ext4 / macOS APFS this is atomic in practice. Hold an advisory `flock(LOCK_EX)` during the write for belt-and-suspenders safety. | HIGH |
| Operation-type vocabulary | Reuse OpenInference `openinference.span.kind` values (`LLM`, `TOOL`, `AGENT`, `GUARDRAIL`, `CHAIN`, `RETRIEVER`, `EMBEDDING`, `EVALUATOR`, `PROMPT`, `RERANKER`). They are STABLE (1.0+) and cleanly include `GUARDRAIL` (which the OTel spec does not). | HIGH |
| Task-type vocabulary | Agent-managed, no external standard. The OpenLLMetry RFC `gen_ai.task.type` suggestions (`research`, `analysis`, `generation`, `review`) are useful seed labels but the spec is a draft RFC, not a registry — do not bind. | HIGH |
| Cron-side consumption | Stdlib Python heredocs only (already in use). No new dependencies. | HIGH |

## Recommended Stack (additions only)

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Bash + stdlib Python 3 (existing) | as installed | Read marker JSONL, join against ledger, scale deltas per marker | The constraint forbids new runtime deps. `json` and `os` modules in stdlib are sufficient for everything we need; Python heredocs are already the JSON tool in `hermes-report.sh`. |
| JSON Lines (jsonlines.org) | Format spec (no version) | Marker file format: one record per agent turn | Append-friendly, line-oriented, parseable by a one-line Python heredoc, no schema framework needed. `jsonlines.org` defines exactly what we need: UTF-8, `\n` separator, no BOM, one JSON value per line. |
| OpenInference span_kind vocabulary | Spec 1.x (Arize-AI) | Authoritative values for `--operation-type` | STABLE since 2024 release. Includes the `GUARDRAIL` value we explicitly need for self-classification overhead — OTel's `gen_ai.operation.name` enum does **not** define this. |
| POSIX `O_APPEND` + `flock(2)` | OS-level | Multi-writer-safe append from agent process | The agent process is a single writer per session, but cron may read concurrently. `O_APPEND` on a local fs (ext4/APFS) with single `write(2)` calls under 4KB is atomic in practice on every system we support; `flock` is a cheap upgrade. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `json` (stdlib) | 3.x | Encode marker records, parse marker lines, parse taxonomy | Always. The default `json.dumps(...)` output is already a single line (no `indent`, no internal `\n`). |
| Python `fcntl` (stdlib) | 3.x | `fcntl.flock(fd, LOCK_EX)` around taxonomy reads/writes | Always for taxonomy mutations. Optional but recommended for marker appends. |
| Python `os.fsync` / `file.flush` | 3.x | Durability after writing the taxonomy file | Only on taxonomy writes. Do not fsync per marker — too expensive at agent latency. |
| `flock(1)` CLI (util-linux on Linux, NOT installed on macOS by default) | — | Shell-level locking from `cron.sh` | **Avoid in cron path** — macOS doesn't ship `flock(1)`. Use Python `fcntl.flock` inside heredocs instead. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Python `unittest` (existing) | Test marker shape, taxonomy shape, split arithmetic | Already wired up via `tests/test_repository.py`. Add `test_marker_file_shape.py`, `test_taxonomy_file_shape.py`, `test_cron_marker_split.py` alongside it. |
| `bash -n` syntax check (existing) | Validate new shell paths | Already invoked from `tests/test_repository.py`. Coverage extends automatically when new scripts land under `skills/revenium/scripts/`. |

### What we are NOT installing

There is no `pip install`, no `npm install`, no new system package. Stdlib Python + existing Bash idioms cover everything.

## File Format Specifications

### Marker file: `~/.hermes/state/revenium/markers/<session_id>.jsonl`

**Spec:**
- One JSON object per line; UTF-8; line terminator `\n`; no BOM
- Each line ≤ 4096 bytes (PIPE_BUF on Linux; below the macOS-observed 256-byte O_APPEND atomicity floor is **not** practical, but local-fs POSIX semantics make single-write `O_APPEND` safe in practice — see Atomicity section)
- `json.dumps(record, ensure_ascii=True, separators=(",",":"))` produces a guaranteed single-line string
- File is per-session — the session ID partitions writers so contention with the cron reader is the only multi-writer concern

**Recommended record schema:**
```json
{"ts":1715515200.123,"task_type":"code_review","operation_type":"LLM","note":"reviewed cron.sh changes"}
```

**Fields:**
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `ts` | float (unix seconds, ms precision) | yes | Matches the timestamp format already used in the ledger (`time.time():.3f`). |
| `task_type` | string | yes | Must come from `~/.hermes/state/revenium/task-taxonomy.json`. Use `unclassified` only as the cron's default for missing markers, not as a label the agent ever writes. |
| `operation_type` | string | yes | One of the OpenInference span_kind enums (see vocabulary section). Defaults: `LLM` for work turns, `GUARDRAIL` for the classification turn itself. |
| `note` | string | no | Short free-text hint for human debugging. Do not parse it. Keep records small. |

**No `session_id` field needed** — it's the filename. Keeping it out of the record keeps each line well under 4KB and makes records context-free.

### Taxonomy file: `~/.hermes/state/revenium/task-taxonomy.json`

**Spec:**
```json
{
  "version": 1,
  "updated_at": 1715515200.123,
  "labels": {
    "code_review":   {"description": "Reviewing existing code for correctness, style, or fit", "first_seen": 1715000000.0},
    "refactor":      {"description": "Restructuring code without changing observable behavior", "first_seen": 1715100000.0},
    "research":      {"description": "Reading docs, exploring the codebase, or searching the web to learn", "first_seen": 1715200000.0}
  }
}
```

**Why a single JSON file (not JSONL):**
- The whole taxonomy must be read atomically by the agent on every classification turn for the lookup-first protocol
- Mutations are infrequent (only when minting a new label); a `read → modify → write-to-tmp → rename` pattern is fine
- `os.rename(tmp, taxonomy_file)` on POSIX is atomic within a single filesystem — the standard atomic-replace idiom

**Write pattern (Python heredoc inside `SKILL.md` guidance, or a small helper script):**
```python
# Read under shared lock, write under exclusive lock + atomic rename
import fcntl, json, os, tempfile, time
TAXONOMY = "/path/to/task-taxonomy.json"

def add_label(name, description):
    with open(TAXONOMY, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        data = json.load(f)
        if name in data["labels"]:
            return False
        data["labels"][name] = {"description": description, "first_seen": time.time()}
        data["updated_at"] = time.time()
        # Atomic replace
        d = os.path.dirname(TAXONOMY)
        with tempfile.NamedTemporaryFile("w", dir=d, delete=False) as tmp:
            json.dump(data, tmp, ensure_ascii=True, indent=2)
            tmp.flush(); os.fsync(tmp.fileno())
            tmpname = tmp.name
        os.rename(tmpname, TAXONOMY)
        return True
```

Two flock(2)'d processes can both think they're the writer briefly because the lock is on the original `TAXONOMY` fd while the rename swaps the inode; we mitigate by re-reading the existing labels inside the lock so a duplicate `add_label` for the same name is a no-op.

## Vocabulary Recommendations

### `--operation-type` (small, fixed vocabulary): use OpenInference span_kind

| Value | Use For | Maps To |
|-------|---------|---------|
| `LLM` | Default for any agent work turn | OpenInference `LLM` |
| `GUARDRAIL` | The classification turn itself (token cost of the feature) | OpenInference `GUARDRAIL` |
| `TOOL` | Pure tool/shell-execution turns (rare in Hermes — most turns mix LLM and tools) | OpenInference `TOOL` |
| `AGENT` | Multi-step agent orchestration if/when introduced | OpenInference `AGENT` |
| `RETRIEVER` | Code search / vector store / grep-heavy turns | OpenInference `RETRIEVER` |
| `CHAIN` | Connector/glue turns between steps | OpenInference `CHAIN` |
| `EVALUATOR` | Self-eval or judge turns | OpenInference `EVALUATOR` |
| `EMBEDDING` | Embedding-only turns | OpenInference `EMBEDDING` |
| `RERANKER` | Reranking turns | OpenInference `RERANKER` |
| `PROMPT` | Template rendering | OpenInference `PROMPT` |

**Why OpenInference over OpenTelemetry `gen_ai.operation.name`:**

1. **Stability.** OpenInference is STABLE (1.x). OTel GenAI is still "Development" status as of 2026 and has had breaking changes. Aligning a wire-format field with an experimental spec is a risk we don't need to take.
2. **`GUARDRAIL` is defined.** OpenInference explicitly defines `GUARDRAIL` ("A span that represents calls to a component to protect against jailbreak user input prompts ..."). We're using it for a slightly different purpose (self-classification overhead), but the analytical intent — "this is overhead, not work" — maps cleanly. OTel has no equivalent.
3. **OTel's enum is verb-shaped, not category-shaped.** OTel's `gen_ai.operation.name` values are `chat`, `create_agent`, `embeddings`, `execute_tool`, `generate_content`, `invoke_agent`, `invoke_workflow`, `retrieval`, `text_completion`. These describe *what API call was made*, not *what kind of work the agent did*. We want the latter for analytics on the Revenium side. OpenInference's span_kind values are category-shaped and a better fit.
4. **Spec compatibility cost is low.** A future migration toward `gen_ai.operation.name` is a flat string-substitution if we want it later. We are not embedding ourselves in the wider OTel ecosystem with these strings — Revenium consumes them as opaque labels.

**OTel mapping for future migration (FYI only, not required now):**
| Our value (OpenInference) | OTel `gen_ai.operation.name` closest |
|---------------------------|--------------------------------------|
| `LLM` | `chat` or `generate_content` |
| `TOOL` | `execute_tool` |
| `AGENT` | `invoke_agent` |
| `EMBEDDING` | `embeddings` |
| `RETRIEVER` | `retrieval` |
| `GUARDRAIL` | (no OTel equivalent — keep our own) |
| `CHAIN` / `EVALUATOR` / `RERANKER` / `PROMPT` | (no OTel equivalents) |

Confidence: HIGH. Confirmed against the OpenInference spec page (Arize-AI) and the OTel registry page.

### `--task-type` (open, agent-managed vocabulary)

There is **no industry-standard controlled vocabulary** for AI agent task types as of 2026. The closest published work:

- **OpenLLMetry RFC #3460** (Traceloop, draft). Proposes `gen_ai.task.type` with suggested values `research`, `analysis`, `generation`, `review`. This is **a draft RFC, not a registry** — its values are seed examples, not a normative vocabulary. Status: HIGH confidence it's a draft, MEDIUM confidence on the exact list.
- **OpenTelemetry GenAI conventions.** Define `gen_ai.workflow.name` and (in the agent-spans page) `gen_ai.agent.name`, but no enumerated task vocabulary.

**Recommendation:** ship a seed taxonomy populated by the agent on first run, drawing from the OpenLLMetry RFC's four labels plus a Hermes-flavored extension. Concrete seeds:

```json
{
  "labels": {
    "research":      {"description": "Reading docs/code or searching to learn before acting"},
    "analysis":      {"description": "Diagnosing a bug, profiling, or characterizing behavior"},
    "generation":    {"description": "Writing new code, tests, or docs from scratch"},
    "review":        {"description": "Reviewing existing code/PRs/diffs"},
    "refactor":      {"description": "Restructuring without changing behavior"},
    "planning":      {"description": "Producing a plan, roadmap, or design doc"},
    "debugging":     {"description": "Reproducing and fixing a defect"}
  }
}
```

The skill-prompt rule (load-bearing, must be verbatim in `SKILL.md`):

> Before classifying, read `task-taxonomy.json`. If an existing label fits, use it exactly as spelled. Mint a new label only if no existing label is appropriate. New labels must be lowercase, snake_case, ≤ 32 chars.

Confidence: HIGH on "no standard exists", MEDIUM on the specific seed list (the four OpenLLMetry suggestions are explicit; the additions are domain judgement).

## Atomicity & Durability Strategy

### What we need

Atomic single-line appends from one writer (the agent process inside Hermes) with a concurrent reader (cron, every 60s, never writes the marker file). One marker file per session — no cross-session contention.

### POSIX guarantees we can rely on

1. **`O_APPEND` semantics** (POSIX): "the file offset shall be set to the end of the file prior to each write" with no intervening operation. This holds for **local filesystems** — ext4 and APFS both honor it.
2. **PIPE_BUF (4096 bytes)** is the spec-guaranteed atomic write size for pipes. The popular belief that it applies to file appends is **not in the spec** but holds in practice on ext4/APFS for short single-write appends.
3. **macOS observed atomicity floor** has been measured as low as 256 bytes in some benchmarks; the reasonable engineering interpretation is "keep records small and don't rely on the 4KB ceiling".
4. **`os.rename(tmp, dst)` on a single filesystem** is atomic on POSIX — used for taxonomy mutations only.

### Practical rules

- **Marker records must be ≤ 1024 bytes serialized.** Well under all observed atomicity floors, keeps lines easy to grep, leaves headroom for the `note` field.
- **Open with `O_APPEND` and do one `write(2)`-equivalent call per record.** In Python that means `open(path, "ab")` and a single `f.write(line.encode("utf-8") + b"\n")` followed by `f.flush()`. No higher-level buffering.
- **Belt-and-suspenders: `fcntl.flock(LOCK_EX)` around the write.** Cost is microseconds, eliminates any residual ambiguity from filesystem-specific edge cases. The cron reader does not need to lock — it reads a snapshot consistent with whatever the file looks like at `open()` time, and torn-write protection from POSIX `O_APPEND` plus our flock means a partial line should never appear.
- **Do not `os.fsync` per marker.** Crash durability for individual markers is acceptable to lose. Markers are recomputable from the next agent turn or simply absent.
- **Do `os.fsync` once on taxonomy mutations.** Taxonomy state is harder to reconstruct and should survive crashes.
- **The cron reader tolerates partial last line.** If the last line doesn't parse, drop it; the next cron cycle will pick it up. (Practical concession; with `O_APPEND` + `flock` we should never see this, but defense in depth is free.)

### Why not pipes / sockets / sqlite

| Alternative | Why not |
|-------------|---------|
| Named pipes (`mkfifo`) | Pipes are point-to-point and require a reader to be present. Cron is not present during agent turns. |
| Unix domain sockets | Adds a daemon. Forbidden by the no-new-runtime-deps constraint. |
| Write to the existing `state.db` | The skill is a pure consumer of Hermes' DB. Hard rule. |
| A new sqlite db owned by the skill | sqlite is already a runtime dep, so technically allowed. But: marker files are append-only event streams the cron reads then archives. sqlite is overkill, and a per-session JSONL file is dramatically easier to inspect with `cat`/`tail`/`jq` from the install. Reserve sqlite for the case where we discover we need queries. |

Confidence: HIGH on POSIX semantics and practical recommendations; MEDIUM on the specific 1024-byte ceiling (a defensive choice, not a measured limit).

## Installation

No new packages.

```bash
# Nothing to install. Stdlib only.
# Verify what is already required:
command -v python3   # >= 3.7 in practice; json/fcntl/os.fsync all stdlib
command -v sqlite3   # already required by hermes-report.sh
command -v revenium  # already required
```

The only filesystem addition is the markers directory:
```bash
mkdir -p "${HERMES_HOME}/state/revenium/markers"
```

This is created by `install-cron.sh` (or wherever the existing install path lives). Path lives in `scripts/common.sh` per the existing discipline.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Per-session JSONL marker file | One global JSONL marker file with `session_id` in each record | If sessions become very short-lived and the per-session inode churn becomes a problem. Trade-off: global file has multi-writer contention from many agent processes. Per-session is the simpler default. |
| OpenInference span_kind values for `--operation-type` | OpenTelemetry `gen_ai.operation.name` values | When/if OTel GenAI conventions reach Stable status AND define a `GUARDRAIL` equivalent. Today, no. |
| Agent-managed flat taxonomy (single file) | Hierarchical taxonomy with category > subtype | If the label set grows past ~50 distinct labels. At that scale a `category/subtype` shape (e.g. `code/review`, `code/refactor`, `docs/write`) might help analytics on the Revenium side. Defer; revisit only if drift becomes visible. |
| `fcntl.flock` in Python heredocs | `flock(1)` CLI tool | If we ever drop the shell-script-from-cron layer and go pure-Python. Today `flock(1)` is missing on stock macOS, so we don't use it. |
| `json.dumps(separators=(",",":"))` | `json.dumps()` default (`", "`, `": "`) | The default is also fine since `indent=None` already produces single-line output. Compact form is just slightly smaller. Cosmetic. |
| Equal split across markers (S2, per PROJECT.md) | Agent-weighted split (S3) or guardrail-estimator (S4) | Already decided in `PROJECT.md`: defer S3/S4 unless attribution drifts noticeably in practice. Stack-level note only: S3 requires the agent to estimate its own per-turn token weight, which it can't reliably do. S4 requires an estimator we'd have to maintain. S2's equal-split is robust to both. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `opentelemetry-sdk`, `opentelemetry-instrumentation-*` Python packages | Heavy. New runtime dep. Marker files do not need to be OTLP spans — Revenium is the sink, not an OTel collector. The wire protocol is `revenium meter completion`, not OTLP. | Stdlib `json`. Adopt OpenInference span_kind **values** without adopting the SDK. |
| `openllmetry-sdk` / Traceloop SDK | Decorator-based instrumentation framework. Requires modifying agent code paths we don't own (Hermes itself). Adds Python dep. | The skill prompt instructs the agent to write markers directly. The agent is the instrumentation. |
| `openinference-semantic-conventions` Python package | We're using ~10 string constants. Pulling the package for that is silly. | Hard-code the OpenInference span_kind strings in `SKILL.md` and `hermes-report.sh`. Add a comment noting the source so future maintainers can audit. |
| `pydantic` or any schema-validation library for marker records | New dep. Validation can be done in 6 lines of stdlib Python in the cron path. | Validate in `hermes-report.sh`'s Python heredoc: check `ts` is float, `task_type` is str, `operation_type` is in the allow-list, skip line on failure with a warn. |
| `jq` as a runtime dep | Not portable; macOS doesn't ship it. Already a pattern violation in the existing scripts (which use Python heredocs for JSON). | Continue the existing Python-heredoc pattern. |
| `inotifywait` / `fswatch` for marker change detection | macOS doesn't ship `inotifywait`; cron-driven design already polls every 60s. Real-time is explicitly out of scope (PROJECT.md). | The 60s cron tick is the trigger. |
| `flock(1)` CLI in scripts | Missing on default macOS install. Adds a portability landmine. | `fcntl.flock` inside Python heredocs (already a stdlib module on every Python we support). |
| `os.O_APPEND` opened then buffered through Python's `open()` text mode | Default text mode buffering may batch multiple records into one write, defeating per-line atomicity. | `open(path, "ab", buffering=0)` then encode to UTF-8 bytes explicitly; **or** `open(path, "a")` + immediate `f.flush()` after every single `f.write(line + "\n")`. The first is stricter. |
| Random UUIDs or trace IDs as marker IDs | Adds churn; markers are positional (filename + line offset). | Identify markers by `(session_id, line_index)` for ledger idempotency, or by `(session_id, ts)` if line index proves fragile under truncation/rotation. |
| Compressing marker files (`.jsonl.gz`) | Premature. Marker files are tiny (one short JSON per turn). | Plain `.jsonl`. Rotate/archive after Hermes session ends if size becomes an issue (it won't). |
| Storing the taxonomy in `state.db` or in `config.json` | Mixes mutation cadences. The taxonomy mutates per-agent-decision; `config.json` is human/setup-managed; `state.db` is Hermes-owned. | Separate `task-taxonomy.json` file declared in `common.sh`. |

## Stack Patterns by Variant

**If the agent process can reliably write its own per-turn token counts** (e.g. Hermes adds an env var or hook later):
- Drop S2 equal-split in the cron; have the agent write `tokens_in/tokens_out` into each marker record
- Cron then attributes per-marker exactly instead of splitting evenly
- Wire shape unchanged; just additional optional fields on each marker line
- Confidence: HIGH that this is a clean upgrade path; the marker schema reserves space for it.

**If a second agent (or a non-Hermes agent) ever writes to the same session's marker file:**
- The `fcntl.flock(LOCK_EX)` guard already handles this — multi-writer becomes safe at the cost of brief blocking
- No schema change needed
- Confidence: HIGH

**If marker files grow huge** (long Hermes sessions, hundreds of substantive turns):
- Rotate per-cron-window: cron reads, processes, then renames `<sid>.jsonl` to `<sid>.<unix_ts>.jsonl.processed` and starts fresh
- Or truncate-after-read with the same flock guarding the boundary
- Confidence: MEDIUM — this is speculative; current expected scale is dozens of markers per session

**If Revenium adds native task-type/operation-type validation server-side:**
- The taxonomy can become advisory rather than load-bearing on this side
- No client-side change needed; we already emit consistent labels
- Confidence: LOW that this happens soon, but planning for it costs nothing

## Version Compatibility

| Package | Constraint | Notes |
|---------|------------|-------|
| Python `json` | stdlib, any 3.x | `json.dumps()` with default args has produced single-line output since Python 2.6. No version risk. |
| Python `fcntl` | stdlib, any POSIX 3.x | macOS and Linux both have it. Windows does not — but `SKILL.md` already declares `platforms: [macos, linux]`. |
| `revenium` CLI | Any version with `meter completion --task-type` and `--operation-type` flags | The CLI surface used here is the same that already exists in `hermes-report.sh:217-235`; we add `--task-type` and `--operation-type` to the same `cmd` array. Verify presence in the same `command -v revenium` precheck. |
| OpenInference span_kind | Spec 1.x (stable) | The values we use are unlikely to change. If they ever do, it's a string-constant swap. |
| OpenTelemetry GenAI semconv | Development | **Not** binding for us. Mentioned only as a future-migration reference. |
| JSON Lines | jsonlines.org spec | No version. The format is stable and trivial. |

## Cross-Reference to Existing Code

| Existing file | What changes |
|---------------|--------------|
| `skills/revenium/scripts/common.sh` | Add `MARKERS_DIR="${STATE_DIR}/markers"` and `TAXONOMY_FILE="${STATE_DIR}/task-taxonomy.json"`. All new paths live here; the path-discipline test enforces this. |
| `skills/revenium/scripts/hermes-report.sh` | Inside the existing `while IFS='\|' read` loop, before building the `cmd` array, read markers for `${sid}` written since `${last_report_ts}`. If none, set `task_type=unclassified`, no `--operation-type`, emit one call as today. If N markers, divide the delta by N, emit N calls each with that marker's `task_type`/`operation_type`. Ledger format extends to `HERMES:<sid>:<total_tokens>:<unix_ts>:<marker_count>` or similar — preserves backward-compat prefix-grep. |
| `skills/revenium/SKILL.md` | Add the lookup-first classification protocol (verbatim text the agent reads on every turn) and the marker-write contract. Add `metadata.hermes.markers_path` advisory note if Hermes consumes it. |
| `tests/test_repository.py` | New tests: marker file shape, taxonomy file shape, cron marker-split behavior under representative inputs (0 markers, 1 marker, N markers, mixed `GUARDRAIL`+`LLM`). |

## Sources

- [OpenTelemetry GenAI registry (`gen_ai.operation.name` enum)](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) — verified enum values; status is "Development". HIGH confidence on values, MEDIUM on stability for external alignment.
- [OpenTelemetry GenAI agent and framework spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/) — confirms `create_agent`, `invoke_agent`, `invoke_workflow`, `execute_tool` as the agent-side enums.
- [OpenTelemetry GenAI semantic conventions overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — confirms Development status as of 2026; `OTEL_SEMCONV_STABILITY_OPT_IN` migration mechanism.
- [OpenInference Semantic Conventions (Arize-AI)](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md) — STABLE 1.x. Defines `LLM`, `EMBEDDING`, `CHAIN`, `RETRIEVER`, `RERANKER`, `TOOL`, `AGENT`, `GUARDRAIL`, `EVALUATOR`, `PROMPT`. HIGH confidence.
- [OpenLLMetry RFC #3460: AI Agent Observability semconv](https://github.com/traceloop/openllmetry/issues/3460) — draft; proposes `gen_ai.task.type` with seed values `research`, `analysis`, `generation`, `review`. HIGH confidence it's a draft, MEDIUM confidence on exact contents (the page is an issue, not a finalized spec).
- [JSON Lines spec (jsonlines.org)](https://jsonlines.org/) — UTF-8, `\n` separator, no BOM, trailing newline recommended-not-required, `.jsonl` extension. HIGH confidence.
- [POSIX write(3p) — atomic O_APPEND semantics](https://man.archlinux.org/man/write.3p) — file offset adjustment and write are atomic with O_APPEND. HIGH confidence on the POSIX guarantee.
- [Are File Appends Really Atomic? (Not The Wizard, 2014, plus 2018 macOS comments)](https://www.notthewizard.com/2014/06/17/are-files-appends-really-atomic/) — practical evidence: 4096-byte atomicity on Linux/ext4 is common but not specified for files; macOS observed as low as 256 bytes in some tests. Drives the "keep records small + flock for belt-and-suspenders" recommendation. MEDIUM-HIGH confidence on the practical guidance.
- [Appending to a File from Multiple Processes (Chris Wellons, nullprogram)](https://nullprogram.com/blog/2016/08/03/) — recommends atomic-record design and direct write(2)/O_APPEND for log appenders; warns against buffered I/O for cross-process appenders. HIGH confidence.
- [flock(2) Linux manual page](https://man7.org/linux/man-pages/man2/flock.2.html) — advisory exclusive lock semantics used for the taxonomy mutation path. HIGH confidence.
- [Python `json` module docs](https://docs.python.org/3/library/json.html) — `json.dumps` default produces single-line output; suitable for JSONL. HIGH confidence.
- Existing repo: `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/hermes-report.sh` — current `cmd` array (lines 216–248) shows where `--task-type`/`--operation-type` will be inserted. HIGH confidence.
- Existing repo: `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/PROJECT.md` — confirms S2 split is decided; defines the GUARDRAIL-for-classification choice. HIGH confidence.

---

*Stack research for: agent-driven task classification + JSONL agent ↔ cron contract on top of an existing zero-dep Bash/Python/sqlite3/revenium-CLI skill.*
*Researched: 2026-05-12*
