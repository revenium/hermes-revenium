# Architecture Research

**Domain:** Hermes-Revenium task-type metering — extending the existing two-half (in-session prompt ↔ out-of-process cron) skill with per-turn task attribution
**Researched:** 2026-05-12
**Confidence:** HIGH for the file-contract / idempotency / atomicity design (verified against existing code and POSIX/Linux O_APPEND semantics); MEDIUM for the taxonomy ergonomics recommendation (best-judgment given agent read/write patterns); HIGH for backward-compat fallthrough (mirrors existing fail-open ledger pattern).

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                  Hermes Agent Session (in-process)                        │
│                                                                           │
│   SKILL.md prompt — extended with classify-and-emit-marker block          │
│   `~/.hermes/skills/revenium/SKILL.md`                                    │
│                                                                           │
│        1. read  budget-status.json   (existing)                           │
│        2. read  task-taxonomy.json   (NEW — lookup-first)                 │
│        3. classify substantive turn  (NEW — agent decides)                │
│        4. write task-taxonomy.json   (NEW — only when minting)            │
│        5. append markers/<sid>.jsonl (NEW — one line per turn)            │
│                                                                           │
└────┬──────────────────┬──────────────────────────┬───────────────────────┘
     │ reads/writes     │ reads (cron only writes  │ reads (cron only
     │ (agent + cron)   │  on fallback / bootstrap)│  reads)
     ▼                  ▼                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│   ~/.hermes/state/revenium/         (state contract surface)              │
│                                                                           │
│   ├── config.json                    alertId, autonomousMode, notify     │
│   ├── budget-status.json             currentValue/threshold/halted        │
│   ├── revenium-hermes.ledger         HERMES:<sid>:<tokens>:<ts>           │
│   │                                  HERMES:<sid>:<tokens>:<ts>:<muid>  ← NEW (extended row)
│   ├── task-taxonomy.json           ← NEW  {label: {description, ...}}    │
│   ├── markers/                     ← NEW  per-session marker streams      │
│   │   ├── <session_id_1>.jsonl                                            │
│   │   └── <session_id_2>.jsonl                                            │
│   ├── revenium-metering.log          cron log                             │
│   └── env                            optional env overrides               │
│                                                                           │
└────┬──────────────────┬──────────────────────────┬───────────────────────┘
     │ reads markers    │ reads taxonomy           │ appends ledger
     │ (new)            │ (fallback validation)    │
     ▼                  ▼                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│   Cron Pipeline (out-of-process, * * * * *)                               │
│                                                                           │
│   `cron.sh` ── `hermes-report.sh` ── `budget-check.sh`                    │
│                       │                                                   │
│                       │ extended: after computing per-session delta T,    │
│                       │   1. enumerate markers for sid written AFTER the  │
│                       │      previous ledger row's timestamp              │
│                       │   2. if N markers found: split T equally, emit    │
│                       │      N `revenium meter completion` calls          │
│                       │      (last call absorbs remainder)                │
│                       │   3. if N == 0: fall back to existing single-call │
│                       │      path with --task-type unclassified           │
│                       │   4. ledger row format extended to capture the    │
│                       │      marker UUIDs reported in this run            │
│                       ▼                                                   │
│                  Revenium API (`revenium meter completion`)               │
└──────────────────────────────────────────────────────────────────────────┘
```

**The contract surface grows by exactly two new files** (`task-taxonomy.json`, `markers/<session_id>.jsonl`) and one extended file format (`revenium-hermes.ledger`). The skill ↔ cron decoupling is preserved: they never call each other, they communicate only via files under `${STATE_DIR}`.

### Component Responsibilities

| Component | Responsibility | New / Existing |
|-----------|----------------|----------------|
| Skill prompt (`SKILL.md`) | Existing budget check; NEW classification block: lookup-first taxonomy read, conservative mint, marker append, GUARDRAIL marker for the classify turn itself | Existing, extended |
| `common.sh` | Single source of truth for paths; NEW vars: `TAXONOMY_FILE`, `MARKERS_DIR`, and helpers `marker_file_for_sid`, `markers_since` | Existing, extended |
| `hermes-report.sh` | Existing per-session delta loop; NEW: factored into helpers (`load_markers_for_session`, `split_delta`, `emit_meter_call`) so the new logic is readable | Existing, refactored |
| Taxonomy file (`task-taxonomy.json`) | Controlled-vocabulary store the agent reads first and writes only when minting | NEW (agent-owned) |
| Marker file (`markers/<sid>.jsonl`) | Per-session append-only stream of `{ts, marker_uuid, task_type, operation_type, ...}` | NEW (agent-write / cron-read) |
| Marker reader helper | Pure-function Python heredoc: given `sid` + `since_ts`, return ordered list of unreported marker records and their UUIDs | NEW (lives inside `hermes-report.sh`) |
| Ledger row | Idempotency key. Extended from `HERMES:<sid>:<total_tokens>:<ts>` to `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>` (legacy rows without the 5th field remain valid) | Existing, extended |

The split between "agent writes / cron reads" for markers and "cron reads / agent writes" for the taxonomy mirrors the existing `budget-status.json` (cron writes / agent reads) shape — same contract, opposite direction.

---

## Recommended Project Structure

No new files in the repo tree — all extensions land in existing files or under existing directories:

```
skills/revenium/
├── SKILL.md                        # EXTENDED: classification + marker emission block
├── references/
│   ├── setup.md
│   ├── troubleshooting.md
│   └── task-taxonomy.md            # NEW: explains the taxonomy contract to the agent
└── scripts/
    ├── common.sh                   # EXTENDED: TAXONOMY_FILE, MARKERS_DIR vars + helpers
    ├── cron.sh                     # unchanged
    ├── hermes-report.sh            # EXTENDED: marker-aware split path + legacy fallback
    ├── budget-check.sh             # unchanged
    ├── clear-halt.sh               # unchanged
    ├── install-cron.sh             # unchanged
    ├── uninstall-cron.sh           # unchanged
    └── prune-markers.sh            # NEW: housekeeping — remove marker files for sessions
                                    #      whose latest-reported ledger row is >N days old
```

### Structure Rationale

- **No new top-level directories.** The repo is a distribution package; reorganizing structure would force a re-doc of installation paths in `docs/installation.md` and `README.md` for no architectural gain.
- **`references/task-taxonomy.md`.** The agent (not the human operator) is the consumer of the taxonomy contract. Reference docs are the existing channel by which `SKILL.md` points the agent at long-form guidance (`SKILL.md` lines 267–270). Adding a third reference is cheap and keeps `SKILL.md` short.
- **`prune-markers.sh`.** Markers will accumulate as sessions die. Pruning is a separable, idempotent housekeeping concern — same flavor as `clear-halt.sh`. Operator-invoked first; can be wired to a less-frequent cron later if needed. Not on the critical path.
- **Runtime layout under `~/.hermes/state/revenium/`**:
  - `task-taxonomy.json` lives at the top of `STATE_DIR` (single file, agent's primary contract).
  - `markers/` is a subdirectory because one file per session keeps the I/O fan-out tractable for both writers (one file lock domain per session) and readers (cron can `ls markers/` and process serially without scanning a giant global log). See "Marker storage tradeoffs" below.

---

## Architectural Patterns

### Pattern 1: Per-session JSONL with O_APPEND-only writes (marker storage)

**What:** Each Hermes session gets its own append-only file at `${MARKERS_DIR}/<session_id>.jsonl`. The agent opens with append mode, writes a single complete JSON object followed by `\n`, closes. Never seeks, never rewrites, never deletes a line.

**When to use:** Producer is single-writer-per-file (the agent is the only writer for a given session), the file is read by a cron that scans once a minute, and individual records are small (well under 4KB).

**Trade-offs:**

| Aspect | Per-session JSONL (recommended) | Single global JSONL | Per-day rotation |
|--------|---------------------------------|---------------------|------------------|
| Writer contention | Zero (one writer per file) | High (every Hermes session contends on one file) | Moderate (every session contends on today's file) |
| Reader scan cost | O(active sessions × markers/session) but trivially parallelizable; reader can `stat` each file and skip ones with mtime older than last ledger ts | O(all markers ever) per cron tick unless reader tracks an offset | O(markers since last ledger ts) but session boundaries cross rotation lines |
| Session affinity | Natural — the file IS the session bucket | Reader must group by `sid` after parsing | Reader must group by `sid` and also stitch across midnight rollover |
| Pruning | Trivial: delete files for sessions older than retention window | Compaction required (rewrite the global file) | File-based, but mixes sessions from many ages in one file |
| Failure isolation | A corrupt line affects one session | A corrupt line can break reader for everyone until skipped | Same risk as global |
| Discoverability | `ls markers/` enumerates sessions cheaply | One file to look at — slightly nicer for `tail -f` debugging | Same as global |

The decisive factor is the existing design's idempotency invariant — the cron reasons per-session, the ledger is keyed by `sid`. Per-session JSONL aligns the marker store with the existing reasoning unit. The other two designs force the reader to do more work to re-impose the same grouping.

**Example marker record:**

```json
{"muid":"01HQ2T8K5RNNNXM6Z6Y9R3X7Q1","ts":1715515443.872,"sid":"f3e2b6...","turn_seq":17,"task_type":"code_review","operation_type":"CHAT","model":"claude-opus-4-7","agent":"Hermes","trace_id":"f3e2b6...:17"}
```

One JSON object per line. The marker UUID (`muid`) is a ULID (sortable by ts) — see Pattern 3.

### Pattern 2: POSIX O_APPEND + sub-PIPE_BUF line writes (atomicity)

**What:** Marker writes use POSIX append mode (`open(path, 'a')` in Python; `>> "${file}"` in bash). Each marker is a single line ≤ a few hundred bytes — far below the Linux 4KB PIPE_BUF threshold under which append-mode writes are observed atomic in practice. The cron reads the whole file (or seeks past a known byte offset and reads to EOF) and never holds a write lock. No advisory locking is required.

**When to use:** Single-writer-per-file (this design), line-oriented records, message size well below the kernel write-atomicity threshold, readers that tolerate trailing partial lines (which never occur in this setup because there's only one writer per file).

**Trade-offs:**
- POSIX guarantees that `O_APPEND` makes the seek-to-end and the write atomic relative to *other modifications of the file offset* — i.e., another writer's append cannot interleave the offset adjustment. POSIX does **not** guarantee that the *bytes* of two concurrent writes are non-interleaved. However, Linux (`ext4`, `xfs`, `apfs` on macOS in our context) honors the practical convention that writes ≤ PIPE_BUF (4KB on Linux, ≥512B on POSIX) issued with `O_APPEND` are observed atomic, which the wider Linux community has documented and depended on for log files for decades. ([POSIX write spec](https://pubs.opengroup.org/onlinepubs/9699919799/functions/write.html), [Appending to a log — Paul Khuong](https://pvk.ca/Blog/2021/01/22/appending-to-a-log-an-introduction-to-the-linux-dark-arts/), [Appending to a File from Multiple Processes — nullprogram](https://nullprogram.com/blog/2016/08/03/))
- In our design, **there is only one writer per marker file** (the agent in that session). The atomicity question collapses to "is one process's append-mode write to its own file atomic from a concurrent reader's perspective?" — and the answer for line-sized writes is yes on every filesystem we ship to.
- The cron reader sees one of two states per line: the full line including `\n` is present, or the line is not present yet. A reader scanning until EOF will never observe a half-written line because the kernel does the write before advancing the file size. (If we were ever in a situation where one write produced bytes that exceeded the kernel write-buffer, we would need to ensure the application calls `write()` exactly once per record; Python's `open(path, 'a').write(line)` for `len(line) < 4096` satisfies this trivially.)

**Why not write-then-rename?**
- Write-then-rename is the right pattern for *replace-existing-file* updates (this is how `budget-check.sh` writes `budget-status.json` — `Path.write_text` plus an atomic rename). It is the **wrong** pattern for append-only logs: you'd be reading + rewriting the whole file on every turn, which destroys the constant-time append property and the cron-reader's ability to seek past previously-read content.

**Why not lock files?**
- Single writer per file removes the need. Adding `flock` would add a failure mode (lock held by a crashed process) without removing any actual contention.

**Example agent-side write (Python heredoc-style, since the agent operates via Hermes file tools):**

```python
import json, os, time, uuid, pathlib
marker = {
    "muid":   f"01H{uuid.uuid4().hex[:23].upper()}",   # or a real ULID
    "ts":     time.time(),
    "sid":    SESSION_ID,
    "turn_seq": TURN_SEQ,
    "task_type": TASK_TYPE,
    "operation_type": OPERATION_TYPE,
    "model":  MODEL,
    "agent":  "Hermes",
    "trace_id": f"{SESSION_ID}:{TURN_SEQ}",
}
path = pathlib.Path(os.path.expanduser(f"~/.hermes/state/revenium/markers/{SESSION_ID}.jsonl"))
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a") as f:                # O_APPEND under the hood
    f.write(json.dumps(marker, separators=(',', ':')) + "\n")
```

Total bytes per write: ~250B. Sub-PIPE_BUF on every platform we target.

### Pattern 3: Marker-UUID idempotency key (cron-side split + ledger semantics)

**What:** Every marker has a `muid` field (a stable opaque identifier — recommendation: ULID for natural lexical sort order matching ts, but any UUID works). The cron, when it splits a session delta T across N markers, records the set of muids it reported in the ledger row. The ledger row format becomes:

```
HERMES:<sid>:<total_tokens>:<unix_ts>:<muid1,muid2,...,muidN>
```

A future cron run that finds the same `(sid, total_tokens)` already in the ledger skips it (existing behavior). A future run that finds `(sid, total_tokens)` higher than any existing ledger row computes the *new* set of markers since the previous ledger row's `<unix_ts>` field, skipping any muids already present in the previous row's tail field.

**When to use:** Idempotency over a fan-out: one external observation (the session token total) becomes N API calls, and we need to be safe under partial-failure re-runs (cron crashed after 3 of 5 meter calls succeeded).

**Trade-offs:**

| Approach | Idempotency on re-run | Cost |
|----------|----------------------|------|
| **Recommended: extend ledger row with reported muids** | Strong — re-run reads the muid set, skips those already reported, emits only the remainder. The existing `(sid, total_tokens)` key still de-dupes "same delta, same set" the way it does today | One column in the ledger; minor grep-and-parse on the cron path |
| Track per-session marker offsets in a sidecar file | Strong — separate `markers-cursor` file maps `sid` → "last reported byte offset" or "last reported muid index" | Extra state file, extra failure modes (cursor and ledger drift), violates the principle that the ledger is the single source of truth for "what has been reported" |
| Scan all markers, dedupe by muid against a recent ledger window | Strong but expensive — requires reading multiple ledger rows per session per tick | Higher CPU on every cron tick; complicates the existing simple `tail -1` lookup |
| Extend the existing `transaction-id` from `${sid}-${total_tokens}` to `${sid}-${total_tokens}-${muid}` | Required regardless of the above choices, because Revenium dedupes on transaction-id and one delta now produces N calls | One-line code change in the meter command |

The recommended ledger extension is backward-compatible: existing rows have four colon-separated fields and the new parsing code treats a missing fifth field as "this row reported one implicit unclassified marker." A new write always emits five fields. The legacy-branding test doesn't care about ledger format.

**Per-meter-call transaction-id (required in all cases):**
- Today: `--transaction-id "${sid}-${total_tokens}"`.
- With markers: `--transaction-id "${sid}-${total_tokens}-${muid}"`. Revenium-side dedupe continues to work; partial-failure re-runs of the same (sid, total_tokens, muid) tuple are idempotent at the API layer too.

### Pattern 4: Backward-compat fallthrough on no markers (preserves existing behavior)

**What:** In `hermes-report.sh`, after the per-session delta is computed, the new code path looks for marker records in `${MARKERS_DIR}/${sid}.jsonl` written between the previous ledger row's `<unix_ts>` and "now". If the file doesn't exist, has zero new markers, or fails to parse, the script falls through to **exactly the existing single-call path**, with one change: it adds `--task-type unclassified` to the meter command. No `--operation-type` flag (defaults to `CHAT` on Revenium's side per existing platform behavior).

**When to use:** Any feature extension to a contract-coupled two-half system where older installs and partial-deployment states (skill updated but cron not yet, cron updated but skill not yet) must not break.

**Trade-offs:**
- Compatibility cost: a one-line check (`[[ -f "${marker_file}" ]] && [[ -s "${marker_file}" ]]`) on the cron side.
- Permanent behavior: even with markers fully deployed, sessions where the agent didn't classify (e.g., a turn that ran in a context where `SKILL.md` was loaded but the classify block didn't fire, or a session that predates this feature) get `unclassified` rather than a missing label. Revenium gets a non-null bucket. This is explicitly listed in `PROJECT.md` as a goal.
- No flag gymnastics: the fallthrough is not a feature flag, it is the natural shape of "no input → known default." That's the existing fail-open philosophy of the skill (e.g., `SKILL.md:85`–`88` for missing `budget-status.json`).

**Pseudocode skeleton inside `hermes-report.sh`:**

```bash
# ... existing delta computation produces delta_input/output/cache_read/cache_write/total/cost ...

marker_file="${MARKERS_DIR}/${sid}.jsonl"
prev_ts="${last_report_ts:-0}"

if [[ -s "${marker_file}" ]]; then
    # Python heredoc: emit JSON array of unreported marker records (muid, task_type, op_type)
    new_markers_json=$(python3 - <<PYEOF || echo "[]"
import json, sys
muids_already_reported = set("${prev_reported_muids:-}".split(",")) - {""}
out = []
with open("${marker_file}") as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try: rec = json.loads(line)
        except json.JSONDecodeError: continue
        if rec.get("ts", 0) <= ${prev_ts}: continue
        if rec.get("muid") in muids_already_reported: continue
        out.append(rec)
print(json.dumps(out))
PYEOF
)
fi

n=$(python3 -c "import json,sys; print(len(json.loads('''${new_markers_json:-[]}''')))")

if [[ "${n}" -gt 0 ]]; then
    # split path: emit N meter calls
    emit_meter_calls_split "${sid}" "${delta_total}" "${delta_input}" "${delta_output}" \
        "${delta_cache_read}" "${delta_cache_write}" "${delta_cost}" "${new_markers_json}"
else
    # fallback path: existing single-call code, with --task-type unclassified
    emit_meter_call_single "${sid}" "${delta_total}" ... --task-type unclassified
fi
```

The big readability win comes from extracting `emit_meter_call_single` and `emit_meter_calls_split` as bash functions inside `hermes-report.sh`. The current 200-line `main()` becomes a much shorter loop that calls one or the other.

### Pattern 5: Equal split with remainder-on-last (S2 implementation)

**What:** Given delta T (total tokens for this report window) and N markers, compute `q = T // N` and `r = T % N`. Emit N meter calls where calls 0..N-2 each report `q` tokens and call N-1 reports `q + r`. Apply the same logic per-field (input, output, cache_read, cache_write, cost). The last call absorbs all remainders to preserve the invariant `Σ(per-call deltas) == per-session delta`.

**When to use:** When you need to split an aggregate value across N rows and rounding matters (it does — Revenium aggregates by sum).

**Trade-offs:**
- Equal split is the documented S2 approximation from `PROJECT.md`. It's deliberately not weighted by agent / marker / model — that's S3/S4, deferred.
- Per-field independence: input, output, cache_read, cache_write, cost each get their own integer-division-plus-remainder. The sum-preservation invariant holds per field.
- Last-marker-absorbs-remainder is biased toward the most recent task. Acceptable bias because (a) remainders are tiny (< N tokens / cost cents); (b) at volume the bias is statistically dominated by the equal-split error itself.

**Example (inline Python heredoc):**

```python
import json, sys
markers = json.loads(MARKERS_JSON)
n = len(markers)
fields = {"in": INPUT, "out": OUTPUT, "cr": CACHE_READ, "cw": CACHE_WRITE, "tot": TOTAL, "cost": COST}
q = {k: v // n for k, v in fields.items() if k != "cost"}
r = {k: v %  n for k, v in fields.items() if k != "cost"}
# cost is a float; split equally and put residual on last
cost_q = round(fields["cost"] / n, 6)
cost_last = round(fields["cost"] - cost_q * (n - 1), 6)
out = []
for i, m in enumerate(markers):
    last = (i == n - 1)
    out.append({
        "muid": m["muid"],
        "task_type": m["task_type"],
        "operation_type": m.get("operation_type", "CHAT"),
        "input":  q["in"]  + (r["in"]  if last else 0),
        "output": q["out"] + (r["out"] if last else 0),
        "cache_read":  q["cr"] + (r["cr"] if last else 0),
        "cache_write": q["cw"] + (r["cw"] if last else 0),
        "total": q["tot"] + (r["tot"] if last else 0),
        "cost":  cost_last if last else cost_q,
    })
print(json.dumps(out))
```

Bash then loops over the JSON array and emits one `revenium meter completion` per element with the appropriate flags.

---

## Data Flow

### Per-turn write flow (agent-side, inside Hermes session)

```
[Substantive turn arrives]
    │
    │  (existing) read budget-status.json → check halted/exceeded
    ▼
[Budget OK → proceed]
    │
    │  (NEW) read task-taxonomy.json
    │     → pick existing label if any fits
    │     → only mint new label if none fit  (strict lookup-first)
    │     → if mint: write taxonomy back (atomic write-then-rename)
    │
    │  (NEW) write GUARDRAIL marker for this classification step itself
    │     (open markers/<sid>.jsonl in append mode, one line)
    │
    ▼
[Do the actual user-requested work]
    │
    │  (NEW) write CHAT marker (or other op_type) for the work turn
    │     (append one line)
    │
    ▼
[Respond to user]
```

Two markers per substantive turn (one GUARDRAIL for the classify step, one CHAT/etc for the work). Trivial turns get zero markers and fall back to `unclassified` on the next cron tick.

### Per-cron-cycle read flow (cron-side, out-of-process)

```
[cron tick — every minute]
    │
    ▼
cron.sh → hermes-report.sh
    │
    ▼
[Query state.db for sessions with non-zero tokens]
    │
    ▼
[For each session sid:]
    │
    ├── lookup last ledger row for sid → (prev_total_tokens, prev_ts, prev_muids)
    │
    ├── if curr_total_tokens ≤ prev_total_tokens → skip
    │
    ├── compute delta_input/output/cache/cost vs prev (existing math)
    │
    ├── (NEW) read markers/<sid>.jsonl, filter:
    │      ts > prev_ts AND muid ∉ prev_muids
    │   → ordered list M = [marker_0, ..., marker_{N-1}]
    │
    ├── if N == 0:
    │      → emit ONE meter call with --task-type unclassified  (fallthrough)
    │      → ledger row: HERMES:sid:total_tokens:now_ts
    │
    ├── if N > 0:
    │      → split delta equally across N markers (remainder on last)
    │      → for each marker m_i:
    │           emit meter call with
    │             --task-type m_i.task_type
    │             --operation-type m_i.operation_type
    │             --transaction-id "${sid}-${total_tokens}-${m_i.muid}"
    │             --trace-id m_i.trace_id  (or existing default)
    │             --agent m_i.agent         (or existing default)
    │      → ledger row: HERMES:sid:total_tokens:now_ts:muid_0,muid_1,...,muid_{N-1}
    │
    └── only append ledger row on full success of all N calls
        (partial-success: append a row with the muids that DID succeed;
         the next tick will see those as already-reported and only retry the rest)
```

### State management invariants

- **`task-taxonomy.json`**: atomic write-then-rename when the agent mints a new label (same pattern as `budget-check.sh:83` uses for `budget-status.json`). Reads tolerate "file missing" (taxonomy hasn't been seeded yet) by treating it as empty.
- **`markers/<sid>.jsonl`**: append-only, never seek, never edit, never delete a line. Lifecycle: created on first marker write for that session, optionally pruned by `prune-markers.sh` once the session is long-dead.
- **`revenium-hermes.ledger`**: still append-only; row format extended but legacy rows remain parseable. Idempotency check at row 71 of `hermes-report.sh` (`grep -q "^HERMES:${sid}:${total_tokens}:"`) continues to work because the prefix is unchanged. New code parses the optional 5th field.
- **No in-memory shared state.** Existing principle preserved.

---

## Scaling Considerations

This is a single-host, per-user agent — there is no horizontal scaling story. The relevant axes are turn volume and session count.

| Scale | Architecture behavior |
|-------|-----------------------|
| Typical (1–10 sessions/host, 10–100 turns/session) | One marker file per session, each a few KB. Cron scans <100KB total each tick. Trivially within budget. |
| Heavy (100 sessions/host, 1000 turns/session) | Marker files reach ~250KB each. Cron `ls markers/` returns 100 names; reader opens and tail-reads each. Still well under one second per tick. |
| Pathological (long-lived sessions, never pruned) | Marker files grow unbounded. `prune-markers.sh` removes files for sessions whose latest ledger row is >N days old. Operator-invoked or wired to a daily cron later. |

### Scaling priorities

1. **First bottleneck:** cron reader doing full-file scans of huge marker files for old sessions. Mitigation: the per-session ledger lookup gives us `prev_ts`; the reader can seek to the first line with `ts > prev_ts` rather than parse the whole file. ULID muids that sort by ts make this even cheaper (line-prefix scan). Build this in from day one — the cost is one extra Python check.
2. **Second bottleneck:** taxonomy file growth fragmenting into similar labels. Mitigation is social (lookup-first discipline in `SKILL.md`), not architectural. `PROJECT.md` explicitly defers auto-merge.
3. **Non-bottleneck:** disk space. Markers at ~250B/turn × 1000 turns = 250KB/session. Hundreds of sessions are a few tens of MB. Trivial.

---

## Anti-Patterns

### Anti-Pattern 1: Putting markers in a single global JSONL

**What people do:** One `~/.hermes/state/revenium/markers.jsonl` file that every Hermes session appends to.
**Why it's wrong:**
- Forces concurrent appends from multiple sessions, putting the O_APPEND-line-atomicity assumption under load it doesn't need to bear.
- Forces the cron reader to group-by-session after parsing instead of treating the file system as the index.
- Makes pruning a rewrite operation (compaction) rather than `rm`.
- Coupling failure: a corrupt or oversized line affects every session's metering for that tick.
**Do this instead:** One file per session, lifecycle bounded by the session it's named for. Sessions are the existing reasoning unit of the cron; align with it.

### Anti-Pattern 2: Calling `revenium meter completion` from inside the agent's turn

**What people do:** Have `SKILL.md` instruct the agent to shell out to `revenium meter completion` directly at classification time.
**Why it's wrong:**
- The agent does not have access to per-turn token counts; `state.db` only exposes per-session cumulatives. The agent literally cannot supply the right `--input-tokens` value.
- Adds a synchronous network call to every substantive turn — defeats the entire point of the cron's once-a-minute batching.
- Couples the two halves directly, violating the load-bearing decoupling principle (CLAUDE.md "Two halves never call each other").
**Do this instead:** Agent emits markers (free, local file appends). Cron remains the sole API caller and does the math against `state.db`.

### Anti-Pattern 3: Auto-mining task labels from chat history at cron time

**What people do:** Cron-side Python heredoc reads the session's chat log, calls an LLM, generates labels post-hoc.
**Why it's wrong:**
- Duplicates the agent's own knowledge (the agent is the best classifier of what it just did).
- Introduces an LLM call into the cron path — cost, latency, and a new failure mode on the metering plane (which is currently fail-open and dependency-light).
- Defeats the controlled-vocabulary goal: each cron-side classify call is one-shot, with no access to the host taxonomy file.
**Do this instead:** Agent classifies in-session (where it has the context), persists to a marker, and the cron faithfully attributes. PROJECT.md "Key Decisions" already commits to this; do not relitigate.

### Anti-Pattern 4: Tracking marker offsets in a sidecar cursor file

**What people do:** A `~/.hermes/state/revenium/markers-cursor.json` mapping `sid → last-reported-byte-offset` to avoid scanning markers since the last ledger row.
**Why it's wrong:**
- Adds a second source of truth ("what have we reported?") that can drift from the ledger.
- Doubles the partial-failure surface: cron crashes between ledger-append and cursor-update → next tick re-reports.
- The ledger row's `ts` already provides the cheap "since when" filter; we don't need a separate cursor.
**Do this instead:** Use the ledger row as the only source of truth. Read `(prev_ts, prev_muids)` from the most recent row for that `sid`; filter markers by those two fields.

### Anti-Pattern 5: Modifying or deleting marker lines after writing them

**What people do:** Add an "edit the last marker if the agent realizes it misclassified" path; or "compact" the marker file by replacing N lines with their sum.
**Why it's wrong:**
- Breaks the O_APPEND atomicity story. Rewriting requires write-then-rename or in-place truncation, both of which create torn-read windows for the cron.
- Breaks idempotency: muids the cron has already reported would silently disappear, leaving the ledger pointing at nonexistent markers.
**Do this instead:** Marker files are append-only. If the agent decides a previous turn was misclassified, it writes a *new* marker reflecting the corrected understanding for the *current* turn; historical markers stay as they are. (Correction semantics are out of scope per PROJECT.md.)

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Revenium platform (`revenium meter completion`) | Sub-process invocation from `hermes-report.sh`, one call per marker | Already integrated. New flags: `--task-type` (from marker), `--operation-type` (from marker, defaults to `CHAT` on platform side), enriched `--transaction-id` (includes `muid`), preserved `--trace-id` / `--agent` (sourced from marker when present, else existing defaults). |
| `~/.hermes/state.db` | sqlite3 read-only query inside `hermes-report.sh` | Unchanged. The agent still cannot see per-turn tokens; this is the architectural reason markers exist. |
| Hermes messaging toolset (halt notifications) | Unchanged | Out of this milestone's scope. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Agent ↔ cron | Filesystem only, under `${STATE_DIR}` | The contract grows by two files (`task-taxonomy.json`, `markers/<sid>.jsonl`) and one extended row format (ledger). No new IPC, no new sockets, no new daemons. |
| `SKILL.md` ↔ Hermes file tools | Read/write via Hermes' built-in file-edit primitives | The agent appends to JSONL via standard file write; the prompt instructs use of append mode. |
| `hermes-report.sh` ↔ Python heredocs | In-process subprocess | Pattern already pervasive in the file. New heredocs: marker reader, equal-split computer. Keep each heredoc small and self-contained. |
| `common.sh` ↔ all scripts | `source` | Add `TAXONOMY_FILE`, `MARKERS_DIR`, optional helpers `marker_file_for_sid`, `ensure_markers_dir`. |

---

## Build Order (Dependency Rationale)

The phase decomposition this architecture implies, ordered by data-flow dependency:

1. **Path foundation (no behavior change).** Add `TAXONOMY_FILE` and `MARKERS_DIR` to `common.sh`. Add `mkdir -p "${MARKERS_DIR}"` near the existing `mkdir -p "${STATE_DIR}"`. Update `test_runtime_paths_are_hermes_native` to assert the new paths are declared in `common.sh`. **Why first:** every later phase reads these vars; landing them in isolation keeps the change small and lets the test machinery move forward independently.

2. **Marker reader + idempotency in the cron (no agent changes yet).** Extend `hermes-report.sh` to: (a) read `markers/<sid>.jsonl` if it exists; (b) implement the new ledger row format (5 fields, backward-compatible parse of 4-field rows); (c) implement the equal-split path; (d) preserve the existing path when N == 0. Test by hand-writing marker files and asserting the cron splits correctly. **Why second:** the cron must understand markers before any agent writes them — otherwise we have a window where the agent writes markers the cron ignores. Building this first means the system stays useful (continues to emit `unclassified`) the moment we deploy.

3. **Taxonomy file + skill-prompt classification block.** Add `references/task-taxonomy.md` describing the contract. Extend `SKILL.md` with the post-budget-check classification block. Seed an initial taxonomy if useful (or let the agent build it). **Why third:** depends on (1) for paths and (2) for the cron's ability to honor the markers the agent will now produce. Once shipped, real markers start flowing.

4. **GUARDRAIL accounting + adjacent-flag enrichment.** Extend the classification block to also write a GUARDRAIL marker for the classify step itself. Wire `--operation-type`, `--agent`, `--trace-id` to flow through from marker fields rather than the current hardcoded defaults. **Why fourth:** measures the cost of the feature itself; only meaningful once markers are flowing in real traffic.

5. **Pruning + housekeeping.** Add `prune-markers.sh`. Document it. Decide whether to wire to a less-frequent cron or leave operator-invoked. **Why last:** no functional dependency on any other phase; purely operational hygiene. Could ship in v2.

6. **Tests for the new contract.** Repository invariant tests for marker-file shape, taxonomy-file shape, cron split behavior under representative inputs. Per `PROJECT.md` "Active" list. **Cross-cutting:** add tests alongside each of phases 1–4 rather than as a single dump at the end.

---

## Concrete File-Path Recommendations

Declared in `skills/revenium/scripts/common.sh` (lines 10–16, alongside existing paths):

```bash
# existing
STATE_DIR="${REVENIUM_STATE_DIR}"
CONFIG_FILE="${STATE_DIR}/config.json"
BUDGET_STATUS_FILE="${STATE_DIR}/budget-status.json"
LEDGER_FILE="${STATE_DIR}/revenium-hermes.ledger"
LOG_FILE="${STATE_DIR}/revenium-metering.log"
ENV_FILE="${STATE_DIR}/env"
STATE_DB="${HERMES_HOME}/state.db"

# new
TAXONOMY_FILE="${STATE_DIR}/task-taxonomy.json"
MARKERS_DIR="${STATE_DIR}/markers"

mkdir -p "${STATE_DIR}" "${MARKERS_DIR}"
```

The agent constructs marker paths as `${MARKERS_DIR}/${session_id}.jsonl`. The cron's reader iterates `${MARKERS_DIR}/*.jsonl` or directly opens by `sid`.

`test_runtime_paths_are_hermes_native` should grep `common.sh` for `task-taxonomy.json` and `markers` strings to enforce the path-discipline invariant the existing test enforces for `state/revenium` and `.hermes`.

---

## Sources

- [POSIX write() spec — Open Group](https://pubs.opengroup.org/onlinepubs/9699919799/functions/write.html) — O_APPEND atomicity definition (HIGH confidence)
- [Appending to a log: an introduction to the Linux dark arts — Paul Khuong](https://pvk.ca/Blog/2021/01/22/appending-to-a-log-an-introduction-to-the-linux-dark-arts/) — Linux O_APPEND practical behavior with sub-PIPE_BUF writes (HIGH confidence)
- [Appending to a File from Multiple Processes — nullprogram](https://nullprogram.com/blog/2016/08/03/) — Cross-platform validation of the single-writer append pattern (HIGH confidence)
- [POSIX write() is not atomic in the way that you might like — Chris Siebenmann](https://utcc.utoronto.ca/~cks/space/blog/unix/WriteNotVeryAtomic) — Caveats on the "PIPE_BUF applies to regular files" folk wisdom (HIGH confidence)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/codebase/ARCHITECTURE.md` — Existing two-half design (HIGH confidence, internal)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/hermes-report.sh` — Current loop shape, lines 41–266 (HIGH confidence, internal)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/skills/revenium/scripts/common.sh` — Path declarations, lines 6–16 (HIGH confidence, internal)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/PROJECT.md` — Project requirements + Key Decisions (HIGH confidence, internal)

---

*Architecture research for: Hermes-Revenium task-type metering extension*
*Researched: 2026-05-12*
