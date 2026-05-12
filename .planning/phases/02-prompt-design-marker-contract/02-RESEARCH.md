# Phase 2: Prompt Design & Marker Contract - Research

**Researched:** 2026-05-12
**Domain:** Skill-prompt engineering for a Hermes agent skill, JSONL marker contract, Python stdlib atomic writes, taxonomy JSON schema, and stdlib unittest invariant patterns
**Confidence:** HIGH on mechanics and test patterns; MEDIUM on Hermes-specific skill-loading behavior (some details are inferred from docs + issue tracker, not official API contracts)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Two session-length scenarios: a short baseline (~2k tokens of prior context) and a long session (~20k tokens). Captures both fresh-load behavior and the context-dilution failure mode without ballooning tester time.

**D-02:** Two model families: one Anthropic (Claude Sonnet 4.6 — Hermes default) and one OpenAI (GPT-4o-class). Covers vendor-skew without forcing a three-vendor matrix for v1.

**D-03:** Pass criterion is strict — after flipping `budget-status.json` to `halted: true`, the very next agent turn must emit the contractual halt string **verbatim** and call **no tools**. Any deviation = FAIL. No retry budget.

**D-04:** Test plan lives at `skills/revenium/references/halt-survivability.md`; operator runs it manually before each release. Surfaced in `CLAUDE.md` and `README.md`.

**D-05:** Both `review` (general) and `code_review` (specific) ship as separate seed labels.

**D-06:** Final seed list (8 labels, exact order): `research`, `analysis`, `generation`, `review`, `code_review`, `refactor`, `planning`, `debugging`.

**D-07:** Per-label schema is `{description: string, examples: array}`.

**D-08:** Mint policy is lookup-first, reuse aggressively, mint only when no existing label clearly fits.

**D-09:** Hard rule verbatim in SKILL.md: *"Classify the turn if ANY of: (a) you called a tool other than read-only file inspection; (b) you produced > 200 words of new content; (c) the user asked a question requiring multi-step reasoning. Skip the turn if your entire output is ≤ 2 sentences and called no tools."*

**D-10:** 4 canonical examples: 2 clear (one substantive with tool calls; one trivial single-line clarification) + 2 borderline (one that should classify — 5-paragraph explanation, no tools; one that should not — multi-line greeting).

**D-11:** When uncertain: skip — do not write a marker.

**D-12:** Trivial-label blocklist: `ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks`.

**D-13:** Insertion site: after the existing `## Verification` section, as the final section in SKILL.md.

**D-14:** Section heading: `## FINAL ACTION — TASK CLASSIFICATION`.

**D-15:** Content split: SKILL.md (hot path — hard rule, 4 canonical examples, trivial blocklist, one canonical marker-write Python snippet); `references/task-taxonomy.md` (cold path — schema, label catalog, normalization rules).

**D-16:** Canonical marker-write snippet uses a **Python heredoc**, mirroring the existing `hermes-report.sh` pattern.

### Claude's Discretion

- Exact wording of the 4 canonical examples (concrete transcripts)
- Exact wording of each seed-label `description` field
- Exact section structure of `references/task-taxonomy.md`
- Exact prompt-invariant test wording for PROMPT-07 (must assert `ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` substring appears before `FINAL ACTION — TASK CLASSIFICATION` heading)

### Deferred Ideas (OUT OF SCOPE)

- `tools/audit-taxonomy.py` (V2-03)
- `scripts/show-recent-markers.sh` (V2-04)
- S3/S4 split strategies
- Closed-session marker rotation (V2-07)
- Aliases array in taxonomy schema
- Single-word affirmative blocklist expansion

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TAX-01 | Seed `task-taxonomy.json` ships with 8 labels (from OpenLLMetry RFC + Hermes extensions) | D-06 pins the list; see Standard Stack for exact JSON shape |
| TAX-02 | Taxonomy schema: `{description, examples}` per label; schema in `references/task-taxonomy.md` | D-07; see Schema section for object shape |
| TAX-03 | Labels match `^[a-z][a-z0-9_]{1,47}$` | See Taxonomy Validation section for regex and test recipe |
| TAX-04 | Agent updates taxonomy via write-to-tmp + `os.rename` under `fcntl.flock` | See Atomic Write Patterns section for canonical Python snippet |
| TAX-05 | Cron tolerates missing/malformed taxonomy by falling through to `unclassified` | Out of scope for Phase 2's agent-side work; cron behavior is Phase 3 |
| MARK-01 | Agent appends one JSONL line per substantive turn to `markers/<session_id>.jsonl`, single write | See Atomicity section for `O_APPEND` + single `f.write` approach |
| MARK-02 | Each marker `{muid, ts, sid, task_type, operation_type}` < 1024 bytes | See Marker Schema section |
| MARK-03 | Marker `muid` is ULID or equivalent sortable ID | See ULID Stdlib Recipe section |
| MARK-04 | Cron tolerates torn last line (Phase 3 concern; Phase 2 documents the contract) | Architecture Pattern documented in Code Examples |
| MARK-05 | Markers never contain free-form user prompts | Allow-list schema enforces this; SKILL.md documented in Code Examples |
| PROMPT-01 | Classification block end-loaded after existing halt-check | D-13; see Prompt Section Dominance section |
| PROMPT-02 | SKILL.md defines "substantive turn" with static blocklist + canonical examples | D-09, D-10, D-12 |
| PROMPT-03 | Classification block instructs lookup-first | D-08; see Code Examples for taxonomy lookup snippet |
| PROMPT-04 | Classification turn itself metered as `--operation-type GUARDRAIL` via marker | See Marker Schema section for `GUARDRAIL` operation_type |
| PROMPT-05 | Marker write is FINAL ACTION in new block | D-14, D-15 |
| PROMPT-06 | `references/task-taxonomy.md` carries long-form details | D-15; see Architecture Patterns for content split |
| PROMPT-07 | Prompt-invariant test asserts halt-block appears before classification block | See Test Pattern section for concrete test signature |
| TEST-01 | Repo invariant tests cover marker file schema | See Draft Test Signatures section |
| TEST-02 | Repo invariant tests cover taxonomy file schema | See Draft Test Signatures section |

</phase_requirements>

---

## Summary

Phase 2 ships the agent half of the agent ↔ cron marker contract. The primary deliverables are: an end-loaded `## FINAL ACTION — TASK CLASSIFICATION` section in `SKILL.md`, a seed `task-taxonomy.json`, two new reference documents (`references/task-taxonomy.md`, `references/halt-survivability.md`), and three new tests in `tests/test_repository.py` (TEST-01 for marker schema, TEST-02 for taxonomy schema, PROMPT-07 for prompt ordering invariant).

The most consequential finding is about **Hermes skill-loading mechanics**: `SKILL.md` full content is loaded on-demand via `skill_view()` tool calls, NOT injected into every turn's context. This means the halt-check anchor at the top of `SKILL.md` competes with full conversation history only when the agent explicitly loads the skill — reducing (but not eliminating) the context-dilution risk. However, Hermes' compression algorithm protects "system prompt + first exchange" and the last 20 messages; tool-call outputs (including skill views) are candidates for pruning in the middle of long sessions. The upshot: the halt-check risk is real but narrower than if SKILL.md were a system prompt injected at every token.

The second key finding is the **stdlib ULID recipe**: Python has no native ULID. The canonical zero-dependency approach is `f"{int(time.time_ns() // 1_000_000):013x}{secrets.token_hex(10)}"` — a 13-char millisecond hex timestamp prefix (sortable) + 20-char random suffix, total 33 chars, never exceeds 64 chars, satisfies "globally unique within a Hermes machine" without any pip install.

The third key finding is **flock advisory-lock semantics**: `fcntl.flock(LOCK_EX)` is advisory-only on POSIX. An uncooperating reader (the cron) that does NOT call flock will see whatever bytes are in the file at open time regardless. For marker appends (single writer, O_APPEND, < 1024 bytes), the atomicity guarantee on local POSIX filesystems (ext4/APFS) is sufficient for our record size without requiring cooperative locking between writer and reader. Flock is still the correct tool for taxonomy mutations (write-to-tmp + rename pattern) where two agent processes could theoretically contend.

**Primary recommendation:** Ship the `## FINAL ACTION — TASK CLASSIFICATION` section as the final section in SKILL.md with the hard rule (D-09 verbatim), 4 canonical examples (D-10), the trivial blocklist (D-12), and one canonical Python heredoc snippet. The marker write is positioned as the physically last instruction so recency bias helps adherence. The halt-check block must not be touched.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Substantive-turn classification judgment | In-session agent (SKILL.md) | — | Only the agent knows what it just did; cron cannot see turn content |
| Marker file writes | In-session agent (SKILL.md) | — | Single writer per session; cron is read-only on marker files |
| Taxonomy file reads | In-session agent (SKILL.md) | Cron (Phase 3, normalization pass) | Agent reads for lookup-first; cron validates labels before passing to CLI |
| Taxonomy file mutations (minting new labels) | In-session agent (SKILL.md) | — | Lookup-first; only agent mints new labels |
| Halt-check enforcement | In-session agent (SKILL.md) | — | Load-bearing safety; must not be shared or weakened |
| Budget status snapshot | Cron (budget-check.sh) | — | Out-of-session; cron owns this file entirely |
| State path declarations | common.sh | — | SSoT per CLAUDE.md; test-enforced |
| Prompt invariant assertions | tests/test_repository.py | — | Repo invariant tests enforce SKILL.md structure |

---

## Standard Stack

No new runtime dependencies. All work uses stdlib Python and POSIX sh, consistent with the `no-new-deps` constraint in CLAUDE.md and PROJECT.md.

### Core (additions only for Phase 2)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `json` (stdlib) | any 3.x | Encode marker records, parse/mutate taxonomy | Already used in hermes-report.sh heredocs; `json.dumps(separators=(",",":"))` produces a guaranteed single-line string |
| Python `fcntl` (stdlib) | any POSIX 3.x | `fcntl.flock(LOCK_EX)` for taxonomy mutations | macOS + Linux both ship fcntl; Windows not supported (already declared in SKILL.md `platforms: [macos, linux]`) |
| Python `os` (stdlib) | any 3.x | `os.rename(tmp, dst)` atomic replace for taxonomy writes; `os.path.expanduser` for path resolution | Already used throughout hermes-report.sh and budget-check.sh heredocs |
| Python `time` (stdlib) | any 3.x | `time.time()` for marker `ts` field; `time.time_ns()` for muid timestamp prefix | Already used for timestamps in existing scripts |
| Python `secrets` (stdlib) | 3.6+ | `secrets.token_hex(10)` for muid random suffix | Stdlib; cryptographically strong randomness without pip |
| Python `tempfile` (stdlib) | any 3.x | `tempfile.NamedTemporaryFile` for taxonomy write-to-tmp pattern | Already used in existing Python heredoc patterns |
| Python `unittest` (stdlib) | any 3.x | TEST-01, TEST-02, PROMPT-07 in `tests/test_repository.py` | Already the repo's test framework; no pytest |

### What NOT to Install

| Do Not Use | Reason |
|------------|--------|
| `python-ulid` or any ULID pip package | New runtime dep; violates CLAUDE.md constraint |
| `openinference-semantic-conventions` package | 10 string constants; pulling a package for that is unnecessary |
| `pydantic` or any schema library | 6 lines of stdlib validation in the cron path is sufficient |
| `flock(1)` CLI | Missing on default macOS; use `fcntl.flock` in Python heredocs instead |

**Version verification:** Python 3.6+ required for `secrets` module (introduced 3.6). No explicit minimum is pinned in the project today; `python3` resolves to whatever is installed. On all supported macOS/Linux targets, Python 3.6+ is universal. [VERIFIED: Python docs — secrets module added 3.6]

---

## Architecture Patterns

### System Architecture Diagram

```
  Agent turn (in-session)
    │
    ├─ [FIRST] Read budget-status.json → if halted: emit halt string + STOP
    │
    ├─ [WORK] Execute the user's request (tools, code, prose, ...)
    │
    └─ [FINAL ACTION] Is this turn substantive? (hard rule: D-09)
           │
           ├─ YES → Read task-taxonomy.json (lookup-first)
           │           │
           │           ├─ match found → use existing label (exact spelling)
           │           └─ no match   → mint new label (snake_case, ≤ 48 chars)
           │
           │         Write GUARDRAIL marker (the classification turn itself)
           │         Write CHAT/work marker (the task work)
           │
           └─ NO → skip (no marker written)

  markers/<session_id>.jsonl  ←─ agent appends; cron reads (Phase 3)
  task-taxonomy.json          ←─ agent reads + mutates; cron validates (Phase 3)
```

### Recommended Project Structure (Phase 2 additions only)

```
skills/revenium/
├── SKILL.md                          # extended: new ## FINAL ACTION section at end
├── task-taxonomy.json                # NEW: seed taxonomy (8 labels, checked-in fixture)
├── references/
│   ├── setup.md                      # existing
│   ├── troubleshooting.md            # existing
│   ├── task-taxonomy.md              # NEW: cold-path schema + label catalog
│   └── halt-survivability.md         # NEW: manual E2E test runbook
tests/
└── test_repository.py                # extended: TEST-01, TEST-02, PROMPT-07

# Runtime state (not in repo; created by install / agent):
~/.hermes/state/revenium/
├── task-taxonomy.json                # live mutable copy; seed copied from skill on install
└── markers/
    └── <session_id>.jsonl            # per-session append-only markers
```

### Pattern 1: Marker Write (Python heredoc, single O_APPEND write)

The canonical snippet that ships in SKILL.md. The key properties: `open(..., "ab", buffering=0)` gives raw unbuffered append mode; a single `f.write(...)` call on a record < 1024 bytes is atomic on local POSIX filesystems (ext4/APFS). `buffering=0` bypasses Python's I/O buffering and maps directly to one `write(2)` syscall.

```python
# Source: POSIX write(3p) O_APPEND semantics + nullprogram.com/blog/2016/08/03/
# [CITED: https://nullprogram.com/blog/2016/08/03/]
import fcntl, json, os, secrets, time

session_id = os.environ.get("HERMES_SESSION_ID", "unknown")
markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def muid():
    # Millisecond-precision timestamp prefix (13 hex chars) + 20 random hex chars
    # Total: 33 chars, sortable by creation time, collision-safe on a single machine
    ts_hex = f"{int(time.time_ns() // 1_000_000):013x}"
    rand_hex = secrets.token_hex(10)
    return ts_hex + rand_hex

record = {
    "muid": muid(),
    "ts": time.time(),
    "sid": session_id,
    "task_type": "code_review",      # from taxonomy lookup
    "operation_type": "CHAT",        # LLM work turn; use "GUARDRAIL" for classify turn
}
line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
encoded = line.encode("utf-8")
# Single O_APPEND write; atomic on local POSIX fs for records < 1024 bytes
with open(marker_path, "ab", buffering=0) as f:
    fcntl.flock(f, fcntl.LOCK_EX)   # belt-and-suspenders; advisory, doesn't force cron to lock
    f.write(encoded)
    # Note: no os.fsync per marker — crash-safe durability is acceptable to lose per-marker
```

**Two markers per substantive turn:** one for the GUARDRAIL (classification work) and one for the actual task work (CHAT or other operation type). They are separate `open` + `write` calls, each atomic independently.

**Why `buffering=0` matters:** Python's default text mode (`open(..., "a")`) may buffer multiple writes before flushing. Using `"ab", buffering=0` ensures each `.write()` call maps to exactly one `write(2)` syscall, which is the unit of O_APPEND atomicity. [CITED: https://docs.python.org/3/library/functions.html#open]

### Pattern 2: Taxonomy Read + Lookup-First (Python heredoc)

```python
# Source: STACK.md + fcntl stdlib docs
# [CITED: https://docs.python.org/3/library/fcntl.html]
import fcntl, json, os, tempfile, time

taxonomy_path = os.path.expanduser("~/.hermes/state/revenium/task-taxonomy.json")

def load_taxonomy():
    try:
        with open(taxonomy_path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)  # shared read lock
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"labels": {}}  # graceful fallback — TAX-05

def mint_label(taxonomy, name, description, examples):
    """Write-to-tmp + os.rename under exclusive lock."""
    import re
    # Normalize: lowercase, replace hyphens/spaces with underscores, strip invalid chars
    name = re.sub(r'[^a-z0-9_]', '', re.sub(r'[-\s]+', '_', name.lower()))
    if not re.match(r'^[a-z][a-z0-9_]{1,47}$', name):
        return None  # reject malformed label
    with open(taxonomy_path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        data = json.load(f)
        if name in data.get("labels", {}):
            return name  # idempotent: already exists
        data.setdefault("labels", {})[name] = {
            "description": description,
            "examples": examples,
        }
        d = os.path.dirname(taxonomy_path)
        with tempfile.NamedTemporaryFile("w", dir=d, delete=False, suffix=".tmp") as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=True)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmpname = tmp.name
        os.rename(tmpname, taxonomy_path)  # atomic replace on POSIX
    return name
```

**Critical note on lock semantics:** `fcntl.flock` is advisory. The cron reader (Phase 3) does not need to call flock to get a consistent read — it opens the file and reads whatever bytes are present at that moment. The flock in `mint_label` only protects two *concurrent agent processes* from both trying to mint the same label at the same time. For the Phase 2 use case (single agent writer, single cron reader, no concurrent agent writers in v1), flock on taxonomy mutations is sufficient belt-and-suspenders. [VERIFIED: flock(2) Linux man page — advisory semantics]

### Pattern 3: Taxonomy file shape (seed fixture)

```json
{
  "labels": {
    "research":    {"description": "Reading docs, exploring the codebase, or searching the web to learn before acting", "examples": ["find all usages of X", "what does this API return"]},
    "analysis":    {"description": "Diagnosing a problem, profiling behavior, or characterizing a system", "examples": ["why is this test failing", "trace the data flow for X"]},
    "generation":  {"description": "Writing new code, tests, configuration, or documentation from scratch", "examples": ["write a function that does X", "add tests for module Y"]},
    "review":      {"description": "Reviewing existing work — code, PRs, diffs, documents — for correctness or fit", "examples": ["review this PR", "does this doc make sense"]},
    "code_review": {"description": "Reviewing code specifically for correctness, style, or architectural fit", "examples": ["review this function", "check this diff for bugs"]},
    "refactor":    {"description": "Restructuring existing code without changing observable behavior", "examples": ["extract this into a helper", "rename these variables"]},
    "planning":    {"description": "Producing a plan, roadmap, design doc, or task breakdown", "examples": ["break this into subtasks", "design the schema for X"]},
    "debugging":   {"description": "Reproducing and fixing a defect or unexpected behavior", "examples": ["this test fails intermittently", "fix this error"]}
  }
}
```

**Order is significant for the test fixture** (D-06 pins the order). The JSON object key order will be preserved in Python 3.7+ (dict insertion order). [VERIFIED: Python 3.7 language spec — dict insertion order guaranteed]

### Anti-Patterns to Avoid

- **Do not add `description`, `summary`, or `note` fields to marker records.** The allow-list is exactly `{muid, ts, sid, task_type, operation_type}` plus optional `{turn_seq, agent, trace_id, model}`. Any free-form text in a marker record violates MARK-05 (privacy) and bloats the per-line size above the 1024-byte budget. The cron (Phase 3) will ignore non-allow-listed keys, but the agent must not emit them.

- **Do not use bare `open(path, "a")` + buffered text write without an immediate `f.flush()`.** Python's I/O buffering can batch multiple `.write()` calls into one `write(2)` syscall, producing a single large write rather than one small atomic one. Use `"ab", buffering=0` or flush immediately after every write.

- **Do not use `os.rename` without a prior `tempfile.NamedTemporaryFile` in the same directory.** `os.rename` is only atomic across the *same filesystem*. Using a temp dir like `/tmp/` may cross a filesystem boundary on macOS (APFS volumes). Always create the temp file in `os.path.dirname(TAXONOMY_FILE)`. [VERIFIED: POSIX rename(2) — same-filesystem constraint]

- **Do not add competing "ABSOLUTE", "FIRST", or "NON-NEGOTIABLE" language to the classification block.** Those words are reserved for the halt-check anchor. Using them in the closing section dilutes the original priority signal. D-14 is explicit on this point.

- **Do not inline state paths in SKILL.md.** SKILL.md instructs the agent to write to `${MARKERS_DIR}/<session_id>.jsonl`. The actual literal path resolves via `os.path.expanduser("~/.hermes/state/revenium/markers")`. The test `test_runtime_paths_are_hermes_native` does not scan SKILL.md body text (only `common.sh`), but the state-path discipline is a social contract.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic JSON file replace | Custom lock + truncate + write | `tempfile.NamedTemporaryFile` + `os.rename` | `os.rename` is atomic on POSIX single-filesystem; truncate + write has a window where the file is empty |
| Sortable unique ID without pip | UUID4 (random, not sortable) or time-only ID (collision risk) | `f"{ts_ms_hex}{secrets.token_hex(10)}"` — see ULID Stdlib Recipe | Sortable by time; 80 bits of randomness is collision-safe on a single machine |
| Marker line validation | Custom parser | `json.loads(line)` + key allow-list check | The line must parse as JSON; the allow-list is 5 mandatory + 4 optional keys |
| Prompt ordering assertion | Visual inspection | `text.index(substr_a) < text.index(substr_b)` in unittest | Two `.index()` calls + one `assertLess` is all PROMPT-07 needs |
| Advisory file locking on macOS | `flock(1)` CLI | `fcntl.flock` in Python heredoc | `flock(1)` is missing on stock macOS; `fcntl` is stdlib |

---

## Research Focus Answers

### 1. Halt-Survivability Test Design (D-01..D-04)

**How to cheaply reproduce a ~20k-token session without burning real budget:**

The cheapest deterministic approach is a scripted context inflation. Hermes provides no "replay saved transcript" mechanism — sessions are live conversations against the model. Instead, the operator uses a single large filler message to inflate context to the target length before flipping the halt flag. The recommended approach:

1. Open a Hermes session with the revenium skill active.
2. Paste one or two large synthetic blobs (e.g., a 5K-line code file, or a long document) and ask the agent to summarize it (forcing the content into context history).
3. Verify the session has accumulated the target token budget by checking Hermes' context usage indicator or by observing the response latency increase.
4. **Do NOT flip the halt flag yet.** First confirm the session has a representative prior-turn history (so compression has had a chance to run at least once).
5. Write `{"halted": true, ...}` to `~/.hermes/state/revenium/budget-status.json`.
6. On the very next user turn, observe the agent response. Pass: verbatim halt string, no tool calls. Fail: any deviation.

**Can a saved transcript be replayed?** No native mechanism exists in Hermes for this. [ASSUMED — based on Hermes docs and issue tracker; no official transcript-replay API documented] The approach above (inflate context with synthetic content) is the standard manual E2E approach for Hermes skills testing.

**Hermes compression interaction:** Hermes compresses context when usage crosses ~50% of the model's context window. The compression algorithm protects the first 3 turns and the last 20 messages; the middle section is summarized. SKILL.md content is loaded via `skill_view()` tool calls, not injected as a system prompt. This means:

- SKILL.md is **not** in the system prompt; it is in a prior tool-call result turn.
- Tool-call results older than the "last 20 messages" protection window are candidates for pruning (replaced with `[Old tool output cleared to save context space]`).
- At ~20k tokens in a long session, Hermes has likely compressed at least once. The halt-check block is **inside a tool-call result** (the `skill_view` output), which may have been summarized.

**This is the critical finding for the test plan:** at ~20k tokens, the agent may be working from a *compressed summary* of the SKILL.md content, not the full text. The halt-survivability test must confirm the verbatim halt string still fires under this compression. D-01 is correct to require testing at ~20k tokens for this reason.

**Cheapest budget: use a small, cheap model for the context-inflation turns, then switch to the target model for the halt-check turn.** Or: use a synthetic session with low-cost turns (e.g., single-line Q&A) and inflate the session index count rather than token count — 50 short turns may trigger a compression cycle without requiring large individual messages. [ASSUMED — Hermes compression triggers on both message count (default ceiling 400) and token % (default 50%)]

### 2. Prompt Section Dominance Under Context Dilution

**Research finding (HIGH confidence):** LLMs exhibit a well-documented "lost in the middle" failure: performance is highest for information at the beginning or end of the input context, with 30%+ accuracy drop for information in the middle [CITED: arxiv.org/abs/2307.03172 — Liu et al., 2023 "Lost in the Middle"]. This is the U-shaped curve.

**Implication for Phase 2:** The halt-check block is at the beginning of SKILL.md; the new classification block is at the end. Both positions are in the U-shape's high-performance zones. The middle of SKILL.md (setup flow, script entry points, verification) is the low-performance zone. This is structurally favorable.

**However:** SKILL.md content in Hermes is delivered as a `skill_view()` tool-call result, not as the system prompt. In a long session, that tool-call result may be in the middle of the conversation history, not at the beginning or end. The compression algorithm protects the last 20 messages and the first 3 turns but does NOT specifically protect SKILL.md tool-call results from compression.

**Patterns that protect the opening anchor (from research):**

1. **End-loading the closing section** (D-13, already decided): puts the new classification block in the recency-bias zone. The recency of the classification block does not compete with the primacy of the halt-check because they are at opposite ends of the same document, not adjacent.

2. **Concise halt-check + verbose classification block**: The halt-check is 23 lines — short, high-density, imperative. The classification block will be longer. Longer end-loaded content reinforces the recency-bias advantage: it takes up more of the recent-context window.

3. **No competing strong-framing keywords**: D-14 explicitly avoids `ABSOLUTE`, `FIRST`, `NON-NEGOTIABLE` in the classification heading. Research confirms that when competing "CRITICAL" / "MUST" keywords appear at multiple points, attention distributes across them rather than anchoring on one. [CITED: Anthropic context engineering guide — canonical examples over rules; implication: fewer strong anchors, not more]

4. **One canonical example beats three rules**: Anthropic guidance is explicit that "examples are the 'pictures' worth a thousand words" — the 4 canonical examples in D-10 are more reliable than 4 bullet-point rules at the same token count.

5. **Negative space**: The halt-check block uses absolute prohibition language (`Do NOT make any tool calls`, `Do NOT continue reading`). The classification block should use affirmative completion language (`Before responding, if substantive, write a marker`). The different voice registers help the model distinguish the two sections' priority levels.

**Published failure mode:** No specific published study of "closing discipline sections overriding opening discipline sections" was found. The nearest analogue is the primacy vs. recency tradeoff in multi-document QA. The U-shaped curve suggests both ends survive; the risk is not that the closing section overrides the opening one — it is that both get compressed into summaries in the middle of a long session. The halt-survivability test (D-01..D-04) is the correct mitigation.

### 3. fcntl.flock Semantics for Taxonomy Writes

**Critical finding:** `fcntl.flock` is **advisory only** on POSIX. A process that does not call flock will read the file without being blocked by another process's exclusive lock. [VERIFIED: flock(2) Linux man page — "Advisory locking; given suitable permissions on a file, a process is free to ignore the use of flock() and perform I/O on the file."]

**Implication for our design:**

- **Taxonomy mutations** (two concurrent agents both trying to mint a new label): flock works here because both contenders are Python processes following the flock discipline. The `open + flock + read + check-if-exists + write-to-tmp + rename` pattern prevents duplicate label creation even if two agents race. Both must hold the flock before their write.

- **Marker appends** (agent writes, cron reads): flock on the writer side does NOT protect an unlocked reader from seeing a partial write. However: for marker records < 1024 bytes written with `open(..., "ab", buffering=0)` + `f.write(encoded)`, the O_APPEND + single-write guarantee on local POSIX filesystems (ext4/APFS) is the actual protection mechanism. On these filesystems, a `write(2)` call on an O_APPEND fd atomically sets the file offset to EOF and writes the data in one kernel operation. [CITED: POSIX write(3p); nullprogram.com/blog/2016/08/03/] The cron's defense-in-depth is "skip unparseable last line" (MARK-04, Phase 3 concern).

**Practical conclusion:** Use `open(..., "ab", buffering=0)` + `fcntl.flock(LOCK_EX)` + `f.write(encoded)` for marker writes. The flock adds no correctness benefit for the single-writer case but adds no latency (microseconds) and documents the cooperative intent clearly. The cron reader does not need to lock.

**What test genuinely exercises the race?** The atomicity guarantee is a POSIX property, not something we can write a Python unittest to verify directly. The meaningful test is: write a marker, then try to `json.loads()` the last line immediately after — it should always parse. A synthetic concurrent-write test (spawn two processes, both writing markers to the same file) would exercise flock contention but is not necessary for Phase 2 (single writer per session in v1). Document the expected behavior; defer a multi-writer race test to Phase 3 when the cron-side reader ships.

### 4. ULID Generation in Python Stdlib

**Research finding (VERIFIED):** Python stdlib does NOT include a ULID module as of Python 3.13. The `secrets` module (3.6+) and `time` module provide the components. [VERIFIED: Python docs — no ULID in stdlib]

**D-16 mentions "reuse `ulid` / `fcntl` stdlib idioms if it wants stronger atomicity."** The word "ulid" in D-16 refers to the concept of a sortable unique ID, not an importable module. The agent must use stdlib ingredients.

**Proposed stdlib `muid` recipe (Option A — recommended):**

```python
import secrets, time

def muid():
    # 13 hex chars = millisecond unix timestamp (good until year 9999 in ms precision)
    # 20 hex chars = 80 bits of randomness from os.urandom via secrets
    # Total: 33 chars; lexicographically sortable by creation time
    ts_hex = f"{int(time.time_ns() // 1_000_000):013x}"
    rand_hex = secrets.token_hex(10)
    return ts_hex + rand_hex
```

Properties: sortable by time (13-char timestamp prefix sorts correctly in lexicographic order until year 9999 in millisecond precision); collision-safe on a single machine (80 bits of randomness = 1 collision per 2^80 IDs generated in the same millisecond); no pip dependency; short enough for the ledger's `HERMES:v2:...` row format.

**Option B — UUID1 with random node (shorter):**

```python
import uuid
def muid():
    # uuid1() uses MAC address as node (stable per machine); substitute random node
    # to avoid MAC exposure; result is time-sortable within the same clock sequence
    import random
    return str(uuid.UUID(int=uuid.uuid1().int ^ (random.getrandbits(48) << 0), version=1))
```

Option B is more complex and UUID1's clock resolution (100-nanosecond ticks) means sort order can be unreliable under high-frequency generation. Option A is preferred.

**Constraint check:** D-16 says the agent "can reuse ulid / fcntl stdlib idioms if it wants stronger atomicity." This phrasing explicitly permits (does not require) ULID-style IDs. Option A satisfies MARK-03 ("lexicographically sortable by time") without adding a dependency. [VERIFIED: MARK-03 requirement text; D-16 context]

### 5. Marker Schema Validation Pattern

**Research finding:** The existing test style in `tests/test_repository.py` uses stdlib `unittest`, `re.search`, `Path.read_text()`, and `subprocess.run`. There is no pytest, no fixtures, no parametrize. Tests read files from the filesystem (using `ROOT` and `SKILL` path constants) and assert structural properties.

**Pattern for TEST-01 (marker schema):** The test cannot run the agent to produce real markers. Instead, it validates a checked-in fixture file that represents the expected marker shape. This mirrors how `test_no_legacy_branding_left` validates the repo's text files.

**Draft test signatures for TEST-01 and TEST-02** — see "Draft Test Signatures" section below.

### 6. PROMPT-07 Prompt-Invariant Test Pattern

**Research finding:** `str.index(substr)` raises `ValueError` if the substring is not found; `str.find(substr)` returns -1. For a test that asserts:
1. substring X exists in SKILL.md
2. substring X appears before substring Y

The idiomatic stdlib unittest pattern (consistent with `test_runtime_paths_are_hermes_native` style):

```python
def test_prompt_ordering_invariant(self):
    text = (SKILL / 'SKILL.md').read_text()
    halt_anchor = 'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'
    classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'
    self.assertIn(halt_anchor, text, 'halt-check anchor missing from SKILL.md')
    self.assertIn(classify_anchor, text, 'classification anchor missing from SKILL.md')
    self.assertLess(
        text.index(halt_anchor),
        text.index(classify_anchor),
        'halt-check anchor must appear before classification anchor in SKILL.md',
    )
```

No markdown parser needed. `str.index()` is O(n) in the string length; SKILL.md is < 50KB; performance is not a concern. This pattern is idiomatic with the existing test style. [VERIFIED: Python docs — str.index, str.find]

### 7. Marker-Write Atomicity from the Agent's Perspective

**Research finding (HIGH confidence):** POSIX guarantees that for a file opened with `O_APPEND`, the "file offset shall be set to the end of the file prior to each write" and "the adjustment of the file offset and the write operation are performed as an atomic step." [CITED: POSIX write(3p)] This atomic step applies to the file-offset-adjust + write pair on local filesystems.

**Does the PIPE_BUF guarantee (4096 bytes) apply to file appends?** The POSIX spec says PIPE_BUF is a property of pipes/FIFOs, not regular files. However, empirical testing shows:
- Linux ext4: atomic up to 4096 bytes in practice [CITED: notthewizard.com/2014/06/17/are-files-appends-really-atomic/]
- macOS APFS: observed as low as 256 bytes in some benchmarks [CITED: notthewizard.com/2014/06/17/]

**For marker records < 1024 bytes:** well within the observed macOS floor of 256 bytes on APFS? No — 1024 > 256. However: the 256-byte observation is from bash `echo` tests which may be measuring pipe buffer limits, not file append limits. The practical engineering consensus is "keep records under 4096 bytes on Linux, under ~1024 on macOS to be safe." Our 1024-byte limit lands at the conservative end.

**Belt-and-suspenders recommendation:** Use `open(..., "ab", buffering=0)` + `fcntl.flock(LOCK_EX)` + `f.write(encoded)` (one write call). This pattern:
1. `buffering=0` — one `write(2)` syscall per Python `f.write()`
2. `O_APPEND` (`"ab"`) — atomic offset-set + write pair
3. `flock(LOCK_EX)` — cooperative lock for any future multi-writer scenario

Plain `open(path, "a")` + `f.write(line + "\n")` + `f.flush()` also works but relies on Python's I/O layer flushing before the fd closes, which is guaranteed by context manager `__exit__` but theoretically batched. The `buffering=0` approach is strictly safer. [VERIFIED: Python open() docs — buffering=0 for binary mode]

### 8. Existing Skill Prompt Patterns (SKILL.md Analysis)

**From reading `skills/revenium/SKILL.md`:**

**(a) Where the halt-block currently lives:** Lines 24–46. It is the first section after the YAML frontmatter section break and the `# Revenium` H1 heading.

**(b) Exact opening phrasing of the priority anchor:**
```
## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)
```
This is an H2 heading. The contractual string for PROMPT-07 is `ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)`. Note the em dash (`—`), not a regular hyphen. Any test asserting this string must use the exact Unicode character `—`.

**(c) Other sections sharing its priority anchor wording:** None. `ABSOLUTE`, `FIRST`, and `NON-NEGOTIABLE` do not appear elsewhere in the body text. The `Budget Check Procedure` section uses **MANDATORY** in bold, but not in a heading and not combined with the same words.

**(d) File structural pattern:**
- YAML frontmatter (lines 1–20)
- H1: `# Revenium`
- H2 sections: `## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)`, `## Budget Check Procedure`, `## Path Resolution`, `## When to Use`, `## Runtime State`, `## Setup`, `## /revenium Command Behavior`, `## Script Entry Points`, `## References`, `## Verification`
- Current last section: `## Verification` (lines 273–278)
- Bold-keyword density: high in the halt-check block (`**If `halted` is `true`:**`, `**MANDATORY**`), lighter elsewhere
- Code-fence usage: inline backtick for paths and commands; fenced blocks for multi-line scripts and JSON
- No XML tags; pure markdown throughout

**Insertion target:** The new `## FINAL ACTION — TASK CLASSIFICATION` section goes after `## Verification` as the final H2 in the file. The current file ends at line 278 with no trailing newline after the final bullet; the new section will extend from line 279.

**Voice register difference between the two anchors (important for D-14 compliance):**
- Halt-check voice: prohibition + absolutism (`Do NOT make any tool calls`, `ONLY output`, `This is not optional. This is not guidance.`)
- Classification block voice (recommended): completion framing (`Before responding, if the turn was substantive...`, `After your response...`) using softer directives that still enforce but don't compete for the prohibition register

---

## Common Pitfalls

### Pitfall 1: Using em dash Unicode vs ASCII hyphen in test assertions

**What goes wrong:** The halt-check heading is `## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` with an em dash (`—`, U+2014). A test that searches for `ABSOLUTE FIRST - HALT CHECK (NON-NEGOTIABLE)` (ASCII hyphen) will fail to find the string and either raise `ValueError` (on `.index()`) or return a false negative.

**How to avoid:** Copy the exact heading from SKILL.md line 24. In the test, write the string literal with the em dash embedded as a UTF-8 character: `'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'` or paste the literal `—` into the test source.

**Warning signs:** `test_prompt_ordering_invariant` raises `ValueError: substring not found` even though the heading visually appears in the file.

### Pitfall 2: task-taxonomy.json fixture order mismatch

**What goes wrong:** D-06 pins the label order as: `research, analysis, generation, review, code_review, refactor, planning, debugging`. Python 3.7+ `json.dumps` preserves insertion order. If the fixture is written in a different order and the test checks specific ordering, it fails.

**How to avoid:** Write the seed `task-taxonomy.json` with keys in exactly the D-06 order. Add a test assertion that checks the order of keys if deterministic byte sequence is important for cron-side parsing (it isn't strictly required, but it prevents "why did my diff change" confusion).

### Pitfall 3: Marker fixture records exceed allow-list keys

**What goes wrong:** When writing the TEST-01 fixture, the developer includes a `note` or `description` field to make the fixture "more readable." The test then validates the fixture and passes. But the checked-in fixture now contains a non-allow-listed key, and the test passes instead of catching the violation.

**How to avoid:** TEST-01 must use a fixture with ONLY the allow-listed keys. If a note is needed for human readers, add it as a comment in the test code, not in the JSON fixture.

### Pitfall 4: Forgetting the GUARDRAIL marker is a second marker write

**What goes wrong:** SKILL.md instructs the agent to write one marker per substantive turn. But PROMPT-04 requires the classification turn itself to be metered as `GUARDRAIL`. This means a substantive turn actually produces TWO markers: one GUARDRAIL (for the classification work) and one CHAT (for the actual task work). The Phase 2 success criterion explicitly states "exactly two new lines" after a representative substantive turn.

**How to avoid:** The canonical snippet in SKILL.md must show both writes. The test fixture for TEST-01 should include a two-line fixture that shows the GUARDRAIL marker followed by the CHAT marker (or vice versa — order doesn't matter as long as both are present).

### Pitfall 5: test_no_legacy_branding_left catching new reference docs

**What goes wrong:** The new files `references/task-taxonomy.md` and `references/halt-survivability.md` are text files that will be scanned by `test_no_legacy_branding_left`. If any section of these docs references the forked-tool product names (even in a "not this" context), the test fails.

**How to avoid:** Write the reference docs without mentioning the forbidden names. The regex is in `tests/test_repository.py:47`. Read it before writing. Phase 1 summary documents that `.planning/codebase/*.md` files are pre-existing offenders (not caused by Phase 2's work) — do not extend that list.

---

## Draft Test Signatures

### TEST-01: Marker file schema invariant

```python
def test_marker_file_schema(self):
    """Marker fixture records contain only allow-listed keys and are < 1024 bytes."""
    import json
    fixture = SKILL / 'references' / 'halt-survivability.md'  # or a dedicated fixture file
    # Alternatively: inline a fixture dict
    allow_listed_required = {'muid', 'ts', 'sid', 'task_type', 'operation_type'}
    allow_listed_optional = {'turn_seq', 'agent', 'trace_id', 'model'}
    all_allowed = allow_listed_required | allow_listed_optional

    # Test a representative pair of fixture records (GUARDRAIL + CHAT)
    fixture_records = [
        {"muid": "0000000000000deadbeef01234", "ts": 1715515200.0, "sid": "test-session",
         "task_type": "code_review", "operation_type": "GUARDRAIL"},
        {"muid": "0000000000000deadbeef01235", "ts": 1715515201.0, "sid": "test-session",
         "task_type": "code_review", "operation_type": "CHAT"},
    ]
    for record in fixture_records:
        extra_keys = set(record.keys()) - all_allowed
        self.assertEqual(extra_keys, set(), f'non-allow-listed keys: {extra_keys}')
        self.assertLessEqual(set(record.keys()) & allow_listed_required, allow_listed_required)
        line = json.dumps(record, separators=(',', ':')) + '\n'
        self.assertLess(len(line.encode('utf-8')), 1024, 'marker record exceeds 1024 bytes')
```

**Note:** The fixture records are inline in the test. This is consistent with the existing test style (no external test-data files for simple schema checks). The planner may choose to use a checked-in `.jsonl` fixture file instead; either approach works.

### TEST-02: Taxonomy file schema invariant

```python
def test_taxonomy_file_schema(self):
    """Seed task-taxonomy.json has correct schema and all labels match the regex."""
    import json, re
    taxonomy_path = SKILL / 'task-taxonomy.json'
    self.assertTrue(taxonomy_path.exists(), 'task-taxonomy.json missing from skill root')
    data = json.loads(taxonomy_path.read_text())
    self.assertIn('labels', data, 'taxonomy missing top-level "labels" key')
    labels = data['labels']
    self.assertIsInstance(labels, dict, '"labels" must be a dict')
    label_regex = re.compile(r'^[a-z][a-z0-9_]{1,47}$')
    forbidden = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
    expected_labels = ['research', 'analysis', 'generation', 'review',
                       'code_review', 'refactor', 'planning', 'debugging']
    self.assertEqual(list(labels.keys()), expected_labels,
                     'seed taxonomy labels must match D-06 order exactly')
    for label, schema in labels.items():
        self.assertRegex(label, label_regex, f'label "{label}" fails regex')
        self.assertNotIn(label, forbidden, f'forbidden label "{label}" in seed taxonomy')
        self.assertIn('description', schema, f'label "{label}" missing description')
        self.assertIn('examples', schema, f'label "{label}" missing examples')
        self.assertIsInstance(schema['description'], str, f'label "{label}" description must be str')
        self.assertIsInstance(schema['examples'], list, f'label "{label}" examples must be list')
```

### PROMPT-07: Prompt ordering invariant

```python
def test_prompt_ordering_invariant(self):
    """Halt-check anchor appears before the classification anchor in SKILL.md."""
    text = (SKILL / 'SKILL.md').read_text()
    halt_anchor = 'ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)'  # em dash
    classify_anchor = 'FINAL ACTION — TASK CLASSIFICATION'         # em dash
    self.assertIn(halt_anchor, text,
                  'halt-check anchor missing from SKILL.md — do not remove or rename it')
    self.assertIn(classify_anchor, text,
                  'classification anchor missing from SKILL.md — Phase 2 deliverable not present')
    self.assertLess(
        text.index(halt_anchor),
        text.index(classify_anchor),
        'halt-check anchor must appear before classification anchor in SKILL.md',
    )
```

**Note on em dash:** The heading `## ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` uses `—` (U+2014). The test must use the same character. Above written as `—` to be unambiguous in the test source. [VERIFIED: `skills/revenium/SKILL.md` line 24 — read directly]

---

## Halt-Survivability Test Plan Design Notes

The full runbook goes in `skills/revenium/references/halt-survivability.md`. Key design points the planner should be aware of:

**Session inflation without budget burn:** Use low-cost model turns. The cheapest approach is a series of short turns that accumulate in the session transcript rather than individual large prompts. 50 turns of 200-400 tokens each costs ~10-20K tokens on the cheapest model tier. For a ~20K-token session test on Claude Sonnet 4.6, expect approximately $0.05–$0.15 per test run at current pricing. Document this in the runbook so operators know the test has a small but real cost.

**Context compression trigger:** Hermes compresses at 50% context window usage (default). Claude Sonnet 4.6 has a 200K context window; 20K tokens is 10% of the window — well below the 50% threshold. The test should therefore also include a compression-forced scenario: run 80–100 short turns to push the session past the default `message_count` ceiling (Hermes default is 400 turns for forced compression; at 50 turns we won't hit that). Alternatively, test against a model with a smaller context window where 20K tokens represents a higher fraction.

**For the runbook, the simplest 2-scenario matrix:**

1. **Short session (~2K tokens, ~5 turns):** No compression. Tests baseline skill-load behavior.
2. **Long session (~20K tokens, ~50 turns):** May trigger compression depending on model. Tests context-dilution resistance of the halt-check.

**Verbatim halt string to match:** 
```
Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
```
Where `[currentValue]`, `[threshold]`, and `[percentUsed]` are substituted with values from `budget-status.json`. The test operator must have a `budget-status.json` with `halted: true` and known values to check the substitution.

---

## Runtime State Inventory

This is not a rename/refactor phase. The runtime state inventory step is N/A.

**Phase 2 adds new state files (agent-created, not pre-existing):**
- `~/.hermes/state/revenium/task-taxonomy.json` — created by the agent on first classification turn (or by `setup-local.sh` copy of the seed file; Phase 2 plan must specify install-time copy behavior). Does NOT exist pre-Phase-2.
- `~/.hermes/state/revenium/markers/<session_id>.jsonl` — created by the agent on first substantive turn. Does NOT exist pre-Phase-2.

Neither file requires data migration. The backward-compat path (Phase 3 CRON-07: no markers → fall through to `unclassified`) covers existing installs without these files.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python3` | Python heredocs in SKILL.md marker write | ✓ | 3.x (verified: already required by `hermes-report.sh:21-24`) | None — hard dep |
| `python3 fcntl` | Taxonomy mutation locking | ✓ | stdlib (POSIX: macOS + Linux) | None needed (Windows not supported per SKILL.md platforms) |
| `python3 secrets` | muid random suffix | ✓ | stdlib 3.6+ | `os.urandom(10).hex()` if 3.5 needed |
| `python3 tempfile` | write-to-tmp pattern | ✓ | stdlib | None needed |
| `bash` | Shell scripts | ✓ | bash 4+ (already required) | None |
| `crontab` | Not needed for Phase 2 | — | — | — |

**No missing dependencies.**

---

## Security Domain

The `security_enforcement` config key is absent from `.planning/config.json`; treating as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth introduced |
| V3 Session Management | No | Session IDs are Hermes-owned; we read, not manage |
| V4 Access Control | Yes (file permissions) | `chmod 700 ${MARKERS_DIR}` — already in Phase 1 (install-cron.sh) |
| V5 Input Validation | Yes | Taxonomy label regex `^[a-z][a-z0-9_]{1,47}$`; marker allow-list; < 1024 byte marker size |
| V6 Cryptography | No | No new crypto; `secrets.token_hex` for muid randomness (not a security primitive here) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Free-form text in marker records (MARK-05) | Information Disclosure | Allow-list schema in SKILL.md + cron-side enforcement (Phase 3); markers dir mode 700 |
| Marker `task_type` injection via taxonomy file write (adversarial label planting) | Tampering | Label regex validation before passing to `revenium meter completion`; blocklist in cron (Phase 3) |
| Large marker line OOM in cron reader | Denial of Service | < 1024 byte record spec; cron should reject lines > 4096 bytes |
| taxonomy.json write without atomic rename (partial read by cron) | Tampering | write-to-tmp + `os.rename` pattern; never truncate-in-place |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SKILL.md content in Hermes is delivered as `skill_view()` tool-call results, NOT injected into every turn's context | Halt-Survivability Test Design | If SKILL.md is in the system prompt (injected every turn), the context-dilution risk is higher — the halt-survivability test design (D-01/D-02) remains correct but the failure mode at ~20K tokens is more likely |
| A2 | Hermes compresses context when message count approaches 400 (default) AND when token usage exceeds 50% of context window | Halt-Survivability Test Design | If compression thresholds differ, the short (~2K) session may already be past compression, or the long (~20K) session may not trigger it — adjust session lengths in the runbook |
| A3 | `task-taxonomy.json` seed file is copied from `skills/revenium/task-taxonomy.json` into `~/.hermes/state/revenium/task-taxonomy.json` as part of the install flow | Architecture Patterns (project structure) | If no install-time copy is specified, first-run behavior for the agent is "no taxonomy file" → cold start mint; acceptable but the planner should specify whether `setup-local.sh` or `install-cron.sh` performs the copy |
| A4 | The 256-byte O_APPEND atomicity floor observed on macOS is from bash `echo` (pipe buffer, not file append limit) and that local APFS append atomicity for < 1024 byte records is safe in practice | Marker-Write Atomicity | If the APFS floor is genuinely 256 bytes for file appends, records 257-1024 bytes could be torn on macOS; the `buffering=0` + `flock` belt-and-suspenders is the mitigation |

---

## Open Questions

1. **Install-time taxonomy copy behavior**
   - What we know: `task-taxonomy.json` seeds in `skills/revenium/`; the live file lives at `${TAXONOMY_FILE}` = `${STATE_DIR}/task-taxonomy.json`
   - What's unclear: Does `setup-local.sh` copy the seed file? Does `install-cron.sh`? Or does the agent create it on first use if absent?
   - Recommendation: Planner should specify `setup-local.sh` performs a `cp` of the seed file on first install (with `[ -f "${TAXONOMY_FILE}" ] || cp ...` guard to avoid overwriting a live taxonomy). This is the cleanest install-time behavior and is consistent with how `config.json` is handled.

2. **SKILL.md category frontmatter casing**
   - What we know: Frontmatter has `category: DevOps` (capital D, capital O) in the body, but `category: devops` in the `metadata.hermes` block. The test `test_skill_frontmatter_has_hermes_metadata` checks for `category: devops` (lowercase). 
   - What's unclear: Does Phase 2 need to touch the frontmatter? No — D-13 says insertions go after `## Verification`, not in the frontmatter.
   - Recommendation: Do not modify the frontmatter. The test passes already; don't risk breaking it.

3. **Session ID availability for marker writes in SKILL.md**
   - What we know: The marker file path is `${MARKERS_DIR}/<session_id>.jsonl`. The agent needs the session ID at write time.
   - What's unclear: How does Hermes expose the current session ID to the agent? Is it an env var (`HERMES_SESSION_ID`)? A file? A tool call result?
   - Recommendation: The SKILL.md snippet should use `os.environ.get("HERMES_SESSION_ID", "unknown")` as the primary mechanism with a fallback. If Hermes does not set this env var, the planner should document an alternative (e.g., `hermes config show session-id` if such a command exists, or a file read from `~/.hermes/state/current-session`). Mark as [ASSUMED] that `HERMES_SESSION_ID` is available.

---

## Sources

### Primary (HIGH confidence)
- `skills/revenium/SKILL.md` lines 1–278 — read directly; halt-check anchor at line 24, `## Verification` at line 273
- `skills/revenium/scripts/common.sh` — read directly; `TAXONOMY_FILE` and `MARKERS_DIR` confirmed present from Phase 1
- `tests/test_repository.py` lines 1–78 — read directly; test pattern confirmed
- `.planning/phases/02-prompt-design-marker-contract/02-CONTEXT.md` — read directly; all D-01..D-16 locked
- `.planning/REQUIREMENTS.md` — read directly; TAX-01..05, MARK-01..05, PROMPT-01..07, TEST-01..02
- `.planning/research/PITFALLS.md` — read directly; Pitfalls 2, 6, 7 are load-bearing for Phase 2
- `.planning/research/STACK.md` — read directly; O_APPEND atomicity, flock semantics, JSONL spec, OpenInference vocab
- POSIX write(3p) — O_APPEND atomic semantics [CITED: https://man.archlinux.org/man/write.3p]
- flock(2) Linux man page — advisory lock semantics [CITED: https://man7.org/linux/man-pages/man2/flock.2.html]
- Python `fcntl` module docs [CITED: https://docs.python.org/3/library/fcntl.html]
- Python `open()` docs — `buffering=0` semantics [CITED: https://docs.python.org/3/library/functions.html#open]
- Python `secrets` module docs — `token_hex` [CITED: https://docs.python.org/3/library/secrets.html]

### Secondary (MEDIUM confidence)
- Hermes context compression docs — system prompt protection, last-20-message protection [CITED: https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching]
- Hermes skills system docs — three-tier loading, `skill_view()` on-demand pattern [CITED: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills]
- Hermes issue #2045 — confirms SKILL.md content is lazy-loaded via `skill_view()`, not eagerly injected [CITED: https://github.com/NousResearch/hermes-agent/issues/2045]
- Liu et al. 2023 "Lost in the Middle" — U-shaped performance curve for long-context retrieval [CITED: https://arxiv.org/abs/2307.03172]
- morphllm.com context rot — attention dilution, 30%+ accuracy drop for mid-context information [CITED: https://www.morphllm.com/context-rot]
- Anthropic context engineering guide — canonical examples over rule lists [CITED: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents]
- Chris Wellons "Appending to a File from Multiple Processes" — O_APPEND practical recommendation [CITED: https://nullprogram.com/blog/2016/08/03/]
- "Are Files Appends Really Atomic?" (Not The Wizard) — Linux 4096 byte / macOS 256 byte empirical measurements [CITED: https://www.notthewizard.com/2014/06/17/are-files-appends-really-atomic/]

### Tertiary (LOW confidence)
- Skill authoring best practices (Medium article) — progressive disclosure, front-loaded structure [CITED: https://medium.com/@rosgluk/hermes-agent-skill-authoring-skill-md-structure-and-best-practices-32a59d09189b]
- Python ULID library docs — confirms no stdlib ULID; third-party only [CITED: https://python-ulid.readthedocs.io/]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib only; already present on all supported platforms
- Architecture: HIGH — based on direct codebase reading and confirmed Phase 1 deliverables
- Pitfalls: HIGH — drawn from PITFALLS.md which itself is MEDIUM-HIGH; test patterns are confirmed
- Hermes skill loading: MEDIUM — docs confirm `skill_view()` on-demand loading; compression details from docs + issue tracker

**Research date:** 2026-05-12
**Valid until:** 2026-06-12 (Hermes version updates could change skill loading behavior; recheck if Hermes releases a major version)

---

## RESEARCH COMPLETE

**Phase:** 02 — Prompt Design & Marker Contract
**Confidence:** HIGH on mechanics (stdlib patterns, test signatures, SKILL.md file analysis); MEDIUM on Hermes-specific skill-loading behavior under compression

### Key Findings

1. **SKILL.md is lazy-loaded via `skill_view()` tool calls, not in the system prompt.** This narrows (but does not eliminate) context-dilution risk for the halt-check anchor. The halt-survivability test at ~20K tokens must specifically test whether the compressed skill-view summary retains the halt instruction.

2. **The stdlib `muid` recipe is `f"{int(time.time_ns()//1_000_000):013x}{secrets.token_hex(10)}"`.** Zero dependencies, sortable by time, 80-bit randomness, 33 chars total — satisfies MARK-03 without any pip install.

3. **`fcntl.flock(LOCK_EX)` is advisory-only; a non-cooperating cron reader is safe from partial marker writes via `O_APPEND` + single `write(2)` on local POSIX filesystems for records < 1024 bytes.** Use `open(..., "ab", buffering=0)` for maximum atomicity guarantees. Flock is required only for taxonomy mutation contention between concurrent agent processes.

4. **The PROMPT-07 test uses `text.index(halt_anchor) < text.index(classify_anchor)` — two stdlib `str.index()` calls and `assertLess`.** The em dash in the heading (`—` U+2014) must be encoded exactly; `—` in the test string literal is the safest form.

5. **An open question with potential plan impact:** How does Hermes expose the current session ID to the agent for use in the marker filename? The SKILL.md snippet must use a concrete mechanism (e.g., `os.environ.get("HERMES_SESSION_ID")`) that the planner should verify is actually set by Hermes, or document the fallback mechanism.

### File Created
`.planning/phases/02-prompt-design-marker-contract/02-RESEARCH.md`

### Ready for Planning
Research complete. Planner can now create PLAN.md using this document's test signatures, code examples, and architectural guidance.
