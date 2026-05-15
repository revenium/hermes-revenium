# Phase 8: Job Declaration Prompt Block - Pattern Map

**Mapped:** 2026-05-15
**Files analyzed:** 5 (1 created, 4 modified)
**Analogs found:** 5 / 5 (every file has an exact in-repo analog)

This is a pure prompt-engineering / config phase. There is no application
runtime — "code" here is prompt prose, a JSON seed file, a bash seed-copy
block, and Python unit tests. Every file in scope has a direct, test-pinned
v1.0 analog in the same repo. Phase 8 should write almost no new mechanism;
its work is *prose* and *mirroring* existing structure.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `skills/revenium/SKILL.md` (MODIFIED — add `## FINAL ACTION — JOB DECLARATION`; rewrite `## ABSOLUTE FIRST — HALT CHECK`) | prompt / config | event-driven (agent turn) | The v1.0 `## FINAL ACTION — TASK CLASSIFICATION` block in the *same file* (`SKILL.md:279-397`) | exact (self-analog) |
| `skills/revenium/job-taxonomy.json` (CREATED — ~8-10 entry seed) | config / data | file-I/O (read+write seed→live) | `skills/revenium/task-taxonomy.json` | exact |
| `skills/revenium/references/halt-survivability.md` (MODIFIED — amend pass criterion) | docs / test-plan | request-response (operator runbook) | itself — the v1.0 pass-criterion / 4-run matrix | exact (self-analog) |
| `examples/setup-local.sh` (MODIFIED — add `job-taxonomy.json` seed→live copy) | config / install script | file-I/O (no-clobber copy) | The `task-taxonomy.json` copy block `examples/setup-local.sh:14-22` | exact (self-analog) |
| `tests/test_repository.py` (MODIFIED — add `job-taxonomy.json` invariants) | test | batch (assertion harness) | `test_taxonomy_file_schema` (`:139-160`), `test_expected_files_exist` (`:56-86`), `test_prompt_ordering_invariant` (`:331-344`) | exact |
| `skills/revenium/references/job-taxonomy.md` (OPTIONAL NEW — planner discretion, A2) | docs | request-response | `skills/revenium/references/task-taxonomy.md` | exact |

## Pattern Assignments

### `skills/revenium/SKILL.md` — new `## FINAL ACTION — JOB DECLARATION` section (prompt, event-driven)

**Analog:** the v1.0 `## FINAL ACTION — TASK CLASSIFICATION` block in the same file (`SKILL.md:279-397`). Mirror its 5-part structure verbatim: a binary **Trigger**, a **Required action sequence**, an `execute_code` snippet, a **Self-check**, worked **Examples**. Add it as a *sibling section immediately after* TASK CLASSIFICATION — do NOT interleave, do NOT edit lines 279-397 (backward-compat invariant; `test_prompt_ordering_invariant` and Phase 7 SCHEMA-04 pin the v1.0 block byte-stable).

**Section header / framing pattern** (`SKILL.md:279-281`) — copy the imperative MANDATORY framing:
```text
## FINAL ACTION — TASK CLASSIFICATION

**MANDATORY — NON-NEGOTIABLE. Execute before EVERY yield back to the user on a substantive turn.** This is closing discipline; it mirrors the HALT CHECK at the top of this file (opening discipline). ...
```

**`execute_code` snippet — session-id resolution ladder** (`SKILL.md:328-342`): copy the 3-tier ladder *verbatim* — `HERMES_SESSION_ID` env → newest `~/.hermes/sessions/*.jsonl` basename → `pseudo-<ts>` fallback. The job marker filename MUST equal the session jsonl basename (the cron reader expects this). Do not invent a new scheme (RESEARCH "Don't Hand-Roll").

**`execute_code` snippet — marker-write core** (`SKILL.md:344-365`): adapt `write_marker()` into `write_job_marker()`. The job marker appends to the *same* `markers/<sid>.jsonl` file as task markers (Phase 7 D-01), so `markers_dir`, `os.makedirs(..., mode=0o700, ...)`, `marker_path`, and the `fcntl.flock(LOCK_EX)` append are reused unchanged:
```python
import fcntl, json, os, secrets, time
# ... session_id resolution ladder copied verbatim from SKILL.md:328-342 ...
markers_dir = os.path.expanduser("~/.hermes/state/revenium/markers")
os.makedirs(markers_dir, mode=0o700, exist_ok=True)
marker_path = os.path.join(markers_dir, f"{session_id}.jsonl")

def write_job_marker(agentic_job_id, job_name, job_type, status):
    # Phase 7 D-03 frozen shape — reader-required: kind, agentic_job_id, job_type, status
    record = {"kind": "job", "ts": time.time(), "sid": session_id,
              "agentic_job_id": agentic_job_id, "job_name": job_name,
              "job_type": job_type, "status": status}
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(marker_path, "ab", buffering=0) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line.encode("utf-8"))
```
Marker shape is FROZEN by Phase 7 D-03 — emit exactly: `{"kind":"job","ts":...,"sid":...,"agentic_job_id":...,"job_name":...,"job_type":...,"status":...}`. The `test_job_marker_schema` test (`test_repository.py:3469-3518`) pins this — reader-required keys are `kind`, `agentic_job_id`, `job_type`, `status`; all keys snake_case; compact `json.dumps(separators=(",",":"))`; line < 1024 bytes.

**`agentic_job_id` entropy suffix:** v1.0 uses `secrets.token_hex` (never `random`) — see `muid()` at `SKILL.md:348-351`. Use `f"{business_label}-{secrets.token_hex(2)}"` → 4 hex chars, matching the `pr-review-fc7a` example.

**Mint-first anti-collapse framing** — copy the prose shape from the v1.0 TASK CLASSIFICATION Step 1 (`SKILL.md:300`): "reuse the closest-fitting existing label. Mint a new `^[a-z][a-z0-9_]{1,47}$` snake_case label only if no existing label fits. Fragmentation ... is permanent harm; minting a slightly-too-broad label is recoverable." D-04 requires this framing be made *strong* with concrete good/bad `job_type` examples (good: `weekly_dependency_upgrade`; bad: `generation`, `task`, `work`, `coding`) to counter the broader ~8-10 entry seed and the `260514-nfb` collapse failure.

**Self-check + Examples blocks:** mirror `SKILL.md:367-397` — a 3-question self-check before yielding, then 4 worked Examples (clear-declare, clear-skip, two borderline). For Phase 8 the examples must spell out the SUCCESS self-verification bar (D-12-OUT): "wrote the fix but didn't run the tests" → `CANCELLED`, not `SUCCESS`.

---

### `skills/revenium/SKILL.md` — rewrite `## ABSOLUTE FIRST — HALT CHECK` (prompt, event-driven)

**Analog:** the v1.0 HALT CHECK block in the same file (`SKILL.md:24-46`).

**Current contractual prose to rewrite** (`SKILL.md:33,37`):
```text
YOUR ENTIRE RESPONSE MUST BE EXACTLY THIS AND NOTHING ELSE:
> Budget enforcement halt is active. $[currentValue] of $[threshold] used ([percentUsed]%). To resume: `bash ~/.hermes/skills/revenium/scripts/clear-halt.sh`
- Do NOT make any tool calls
- Do NOT fetch any data
...
```

**Pattern 4 — mandated single first-step (D-14):** rewrite so a `halted:true` turn does exactly two things in order: (1) one `execute_code` call writing a degraded-deterministic `CANCELLED` job marker *only if an arc is in progress* (D-16 arc-in-progress guard), (2) emit the verbatim halt string — nothing else. Reword "Do NOT make any tool calls" → "make exactly one tool call: the mandated `CANCELLED` marker write below, then nothing else." Keep the verbatim halt string anchor dominant — it remains step 2 and the agent answers nothing.

**Degraded-deterministic halt marker (D-15)** — emit a near-fixed marker so the halt turn carries almost no reasoning load:
```json
{"kind":"job","ts":1747300000.12,"sid":"abc123","agentic_job_id":"budget-halt-9c3e","job_name":"Arc interrupted by budget halt","job_type":"interrupted","status":"CANCELLED"}
```
`agentic_job_id` = `"budget-halt-" + secrets.token_hex(2)`; `job_type` = literal `interrupted` (seed this entry in `job-taxonomy.json` per A4 so the halt turn never touches the taxonomy file); `status` = fixed `CANCELLED`. Reuse the same `write_job_marker()` core and session-id ladder; do NOT add a taxonomy read on the halt path.

---

### `skills/revenium/job-taxonomy.json` (created — config/data, file-I/O)

**Analog:** `skills/revenium/task-taxonomy.json` — copy its schema exactly.

**Schema pattern** (`task-taxonomy.json:1-9`):
```json
{
  "labels": {
    "research": {
      "description": "Reading docs, exploring the codebase, or searching the web to learn before acting",
      "examples": [
        "find all usages of X",
        "what does this API return"
      ]
    }
  }
}
```
Single top-level `labels` key → object mapping label → descriptor with exactly two keys: `description` (string) and `examples` (list). Same `^[a-z][a-z0-9_]{1,47}$` label regex (`task-taxonomy.md:51`). Same blocklist discipline — never seed `ack`/`acknowledgment`/`greeting`/`confirmation`/`hello`/`thanks` (`task-taxonomy.md:62-70`).

**Content (D-04, ~8-10 entries — planner discretion):** e.g. `feature_development`, `bug_fix`, `code_review`, `refactoring`, `research`, `debugging`, `testing`, `documentation`, `devops`, `planning`. Per A4, also seed `interrupted` for the degraded halt marker so D-15's halt path never triggers a fresh mint.

**Live-mutation (reuse-or-mint persist) pattern** — `task-taxonomy.md:100-126` `mint_label()`: `flock(LOCK_EX)` + write to a tmp file *in the same directory* + `os.fsync` + `os.rename` (atomic POSIX replace). The JOB DECLARATION snippet persists a newly-minted `job_type` back to `JOB_TAXONOMY_FILE` with this exact pattern — never an in-place `json.dump`. The snippet must fail-open (treat as empty taxonomy, mint freely) if `JOB_TAXONOMY_FILE` is absent (RESEARCH Runtime State Inventory — backward-compat for installs that never re-run setup).

---

### `examples/setup-local.sh` (modified — install script, file-I/O)

**Analog:** the `task-taxonomy.json` seed→live copy block at `examples/setup-local.sh:14-22`.

**No-clobber copy pattern** (`setup-local.sh:14-22`):
```bash
STATE_DIR_DEFAULT="${REVENIUM_STATE_DIR:-${HOME}/.hermes/state/revenium}"
TAXONOMY_DEST="${REVENIUM_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/task-taxonomy.json}"
mkdir -p "$(dirname "${TAXONOMY_DEST}")"
if [[ ! -f "${TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/task-taxonomy.json" "${TAXONOMY_DEST}"
  echo "Seeded ${TAXONOMY_DEST}"
else
  echo "Taxonomy already exists at ${TAXONOMY_DEST}, not overwriting"
fi
```
Add a parallel block for `job-taxonomy.json`, using the `REVENIUM_JOB_TAXONOMY_FILE` env override (matching `common.sh:25`):
```bash
JOB_TAXONOMY_DEST="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/job-taxonomy.json}"
if [[ ! -f "${JOB_TAXONOMY_DEST}" ]]; then
  cp "${REPO_ROOT}/skills/revenium/job-taxonomy.json" "${JOB_TAXONOMY_DEST}"
  echo "Seeded ${JOB_TAXONOMY_DEST}"
else
  echo "Job taxonomy already exists at ${JOB_TAXONOMY_DEST}, not overwriting"
fi
```
The block must preserve `set -euo pipefail` (`setup-local.sh:2`) and stay bash 3.2-safe (`cp` + `[[ ! -f ]]` — already 3.2-compatible; do not introduce bash 4 syntax). `setup-local.sh` is the only v1.0 seed-copy path — `install-cron.sh` does NOT copy taxonomies (A1, verified).

---

### `tests/test_repository.py` (modified — test, batch)

**Analog 1 — file presence:** `test_expected_files_exist` (`:56-86`). Add `SKILL / 'job-taxonomy.json'` to the `expected` list (sits beside `SKILL / 'task-taxonomy.json'` at `:64`):
```python
expected = [
    ...
    SKILL / 'task-taxonomy.json',
    SKILL / 'job-taxonomy.json',          # Phase 8 — job-declaration seed
    ...
]
```

**Analog 2 — schema test:** add `test_job_taxonomy_file_schema`, mirroring `test_taxonomy_file_schema` (`:139-160`):
```python
def test_job_taxonomy_file_schema(self):
    """Seed job-taxonomy.json has correct schema and all labels match the regex."""
    import json, re
    taxonomy_path = SKILL / 'job-taxonomy.json'
    self.assertTrue(taxonomy_path.exists(), 'job-taxonomy.json missing from skill root')
    data = json.loads(taxonomy_path.read_text())
    self.assertIn('labels', data, 'taxonomy missing top-level "labels" key')
    labels = data['labels']
    self.assertIsInstance(labels, dict, '"labels" must be a dict')
    label_regex = re.compile(r'^[a-z][a-z0-9_]{1,47}$')
    forbidden = {'ack', 'acknowledgment', 'greeting', 'confirmation', 'hello', 'thanks'}
    for label, schema in labels.items():
        self.assertRegex(label, label_regex, f'label "{label}" fails regex')
        self.assertNotIn(label, forbidden, f'forbidden label "{label}" in seed taxonomy')
        self.assertIn('description', schema, f'label "{label}" missing description')
        self.assertIn('examples', schema, f'label "{label}" missing examples')
```
Note: unlike `test_taxonomy_file_schema:152` (which pins an *exact* ordered label list), the job seed list is planner discretion (D-04) — the new test should validate schema + regex + blocklist but NOT pin an exact `expected_labels` list (or pin it loosely as a count).

**Analog 3 — ordering invariant:** extend `test_prompt_ordering_invariant` (`:331-344`). The existing test pins `halt_anchor` index < `classify_anchor` index. Add the new `FINAL ACTION — JOB DECLARATION` anchor and assert it sits *after* the classify anchor (keeps the halt anchor dominant — Pitfall 2):
```python
job_anchor = 'FINAL ACTION — JOB DECLARATION'
self.assertIn(job_anchor, text, 'job-declaration anchor missing from SKILL.md')
self.assertLess(text.index(classify_anchor), text.index(job_anchor),
                'job-declaration anchor must appear after classification anchor')
```

**Regression tests already covering Phase 8 (do not modify):** `test_job_marker_schema` (`:3469`) and `test_job_marker_does_not_alter_task_completion_argv` (`:3520`) already pin the `kind:"job"` shape and v1.0 byte-identical metering — the JOB DECLARATION snippet must emit markers conforming to `test_job_marker_schema`'s fixture. `test_runtime_paths_are_hermes_native` (`:118`) already asserts `JOB_TAXONOMY_FILE=` and `job-taxonomy.json` are in `common.sh` (Phase 7 D-13) — no `common.sh` change needed in Phase 8.

---

### `skills/revenium/references/halt-survivability.md` (modified — docs/test-plan)

**Analog:** itself — the v1.0 pass criterion and 4-run matrix.

**Current pass criterion to amend** (`halt-survivability.md:14-23`):
```text
## Pass criterion
After flipping `budget-status.json` to `halted: true`, the very next agent turn must:
- Emit the contractual halt string **verbatim** with the actual substituted values
- Call **no tools**
- Fetch **no data**
...
```

**D-14 amendment:** change "Call **no tools**" → "exactly one tool call permitted (the mandated `CANCELLED` job-marker write); the verbatim halt string still fires; no other tools, no data fetch, no answering the question." This MUST land in the same plan/wave as the SKILL.md halt-block rewrite (Pitfall 5 — a stale runbook FAILs the gate every run and blocks release). The 4-run matrix at `:38-47` (2 session lengths × 2 model families) and the per-scenario steps reference the same criterion — update each in lockstep.

---

### `skills/revenium/references/job-taxonomy.md` (OPTIONAL — planner discretion, A2)

**Analog:** `skills/revenium/references/task-taxonomy.md` (full file). If the planner ships a parallel reference doc, mirror its sections: What this is, Schema, Label normalization rules, Blocklist, Mint policy, Atomic write pattern, Label catalog. Per A2 this is optional — D-04's "mirror the v1.0 machinery" can be satisfied by reusing `task-taxonomy.md`'s rules in-prompt.

## Shared Patterns

### Atomic taxonomy write (reuse-or-mint persist)
**Source:** `skills/revenium/references/task-taxonomy.md:100-126` (`mint_label`)
**Apply to:** the JOB DECLARATION `execute_code` snippet when persisting a minted `job_type` back to `JOB_TAXONOMY_FILE`.
```python
import fcntl, json, os, tempfile, re
# normalize: hyphens/spaces -> underscore, lowercase, strip non-[a-z0-9_]
name = re.sub(r'[^a-z0-9_]', '', re.sub(r'[-\s]+', '_', name.lower()))
if not re.match(r'^[a-z][a-z0-9_]{1,47}$', name):
    return None  # reject malformed label
with open(taxonomy_path, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    data = json.load(f)
    data.setdefault("labels", {})[name] = {"description": ..., "examples": ...}
    d = os.path.dirname(taxonomy_path)
    with tempfile.NamedTemporaryFile("w", dir=d, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=True)
        tmp.flush(); os.fsync(tmp.fileno()); tmpname = tmp.name
    os.rename(tmpname, taxonomy_path)  # atomic POSIX same-filesystem replace
```
The tmp file MUST be in the same directory as the target — `os.rename` is only atomic same-filesystem (`task-taxonomy.md:96-98`). Never write to `/tmp`.

### Append-only JSONL marker write
**Source:** `skills/revenium/SKILL.md:353-359` (`write_marker`)
**Apply to:** both the JOB DECLARATION block and the rewritten HALT CHECK block.
`open(marker_path, "ab", buffering=0)` + `fcntl.flock(LOCK_EX)` + compact `json.dumps(..., separators=(",",":"), ensure_ascii=True)`. POSIX `O_APPEND` + advisory flock is the repo idiom — do not hand-roll a read-modify-write or lockfile dance.

### Session-id resolution ladder
**Source:** `skills/revenium/SKILL.md:328-342`
**Apply to:** every `execute_code` snippet that writes a marker (job declaration + halt path).
3-tier ladder: `HERMES_SESSION_ID` env → newest `~/.hermes/sessions/*.jsonl` basename → `pseudo-<int(time.time())>`. Copy verbatim; the cron's marker reader keys attribution on the marker filename matching the session jsonl basename. Inherited limitation (a `pseudo-` id is not cron-attributable) — do not attempt to "fix" it in Phase 8.

### Entropy primitive
**Source:** `skills/revenium/SKILL.md:348-351` (`muid` uses `secrets.token_hex`)
**Apply to:** `agentic_job_id` suffix minting.
Always `secrets.token_hex` — never `random`. `secrets.token_hex(2)` = 4 hex chars (`fc7a`-shaped suffix).

### State-path discipline
**Source:** `skills/revenium/scripts/common.sh:25` (`JOB_TAXONOMY_FILE` already declared, Phase 7 D-13)
**Apply to:** all of Phase 8. NO new state path is declared — `JOB_TAXONOMY_FILE` and `MARKERS_DIR` already exist in `common.sh`. The seed-copy block in `setup-local.sh` honors the `REVENIUM_JOB_TAXONOMY_FILE` override. `test_runtime_paths_are_hermes_native` enforces single-source path discipline.

### Stdlib-only constraint
**Source:** `CLAUDE.md` "Python Heredocs Inside Bash"
**Apply to:** the JOB DECLARATION `execute_code` snippet.
Only `fcntl, json, os, secrets, time, re, tempfile` — all Python stdlib. No `pip`-installable imports, no new runtime dependency.

## No Analog Found

None. Every file in Phase 8 scope has an exact, test-pinned v1.0 analog within the same repository. This is the intended shape of a "mirror the v1.0 machinery" phase — the planner should copy structure, not invent it.

## Metadata

**Analog search scope:** `skills/revenium/` (SKILL.md, references/, task-taxonomy.json, scripts/common.sh), `examples/setup-local.sh`, `tests/test_repository.py`
**Files scanned:** 7 (SKILL.md sections, task-taxonomy.md, task-taxonomy.json, setup-local.sh, common.sh, halt-survivability.md, test_repository.py targeted sections)
**Pattern extraction date:** 2026-05-15
