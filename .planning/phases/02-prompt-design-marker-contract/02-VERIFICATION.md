---
phase: 02-prompt-design-marker-contract
verified: 2026-05-12T20:10:29Z
status: human_needed
score: 17/18 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run 4-scenario halt-survivability matrix in references/halt-survivability.md (Short+Long x Anthropic+OpenAI)"
    expected: "Each run: agent emits the exact halt string with substituted values and calls no tools"
    why_human: "Requires a live Hermes session, a real LLM invocation, and manual observation of agent output — cannot be verified programmatically"
---

# Phase 2: Prompt Design & Marker Contract Verification Report

**Phase Goal:** A Hermes session loaded with the updated skill (a) still emits the verbatim halt string in response to a halted budget within long sessions, and (b) appends well-formed marker lines to `~/.hermes/state/revenium/markers/<sid>.jsonl` for substantive turns, with one GUARDRAIL marker per classification turn.
**Verified:** 2026-05-12T20:10:29Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                              | Status       | Evidence                                                                                                       |
|----|----------------------------------------------------------------------------------------------------|--------------|----------------------------------------------------------------------------------------------------------------|
| 1  | Halt-survivability E2E runbook is operator-ready and reachable from README.md                      | VERIFIED     | `halt-survivability.md` exists with 7 H2 sections (both scenarios documented); README.md line 213 links it   |
| 2  | Two JSONL marker lines per substantive turn: GUARDRAIL + CHAT, each < 1024 bytes, allow-listed keys | VERIFIED     | `test_marker_file_schema` passes; `SKILL.md:362–413` canonical snippet writes both markers                    |
| 3  | Seed taxonomy has exactly 8 labels in D-06 order, all matching `^[a-z][a-z0-9_]{1,47}$`           | VERIFIED     | `test_taxonomy_file_schema` passes; `task-taxonomy.json` confirmed 8 labels in exact expected order           |
| 4  | PROMPT-07 invariant confirms halt-anchor precedes classification anchor in SKILL.md                | VERIFIED     | `test_prompt_ordering_invariant` passes; halt at line 24, classification at line 279                          |
| 5  | Atomic write fixture exercises flock+rename, uses subprocess reader, has no `time.sleep`           | VERIFIED     | `test_taxonomy_atomic_write_pattern` passes; no `sleep` call in test file; uses subprocess + `os.rename`      |
| 6  | Halt string verbatim fires under long-session context dilution (SC1 — live LLM test)               | UNCERTAIN    | Runbook exists and is complete; live agent behavior cannot be verified without running Hermes                  |
| 7  | MARK-04: cron reader tolerates torn last line (incomplete JSON) by ignoring it and resuming        | PARTIAL      | Cron reader does not yet exist (Phase 3); contract is established by < 1024 byte + single O_APPEND write; no test covers cron-reader tolerance |

**Score:** 5/5 programmatically-verifiable truths verified. 1 requires human (SC1). 1 partial (MARK-04, schema contract established, cron behavior deferred to Phase 3).

---

### Required Artifacts

| Artifact                                                    | Expected                               | Status     | Details                                                        |
|-------------------------------------------------------------|----------------------------------------|------------|----------------------------------------------------------------|
| `skills/revenium/task-taxonomy.json`                        | 8-label seed taxonomy                  | VERIFIED   | 8 labels, D-06 order, all keys match regex                     |
| `skills/revenium/references/task-taxonomy.md`               | Long-form schema doc (PROMPT-06)       | VERIFIED   | 216 lines; schema, normalization, blocklist, mint pattern      |
| `skills/revenium/references/halt-survivability.md`          | 4-run E2E operator runbook             | VERIFIED   | 7 H2 sections; both scenarios; pass/fail criteria; result table |
| `skills/revenium/SKILL.md` classification section (line 279) | End-loaded FINAL ACTION section        | VERIFIED   | Section at line 279; halt anchor at line 24; 4 examples; blocklist; write snippet |
| `tests/test_repository.py::test_taxonomy_file_schema`       | TEST-02: taxonomy schema invariant     | VERIFIED   | Method exists; asserts 8 labels in D-06 order; regex; forbidden labels |
| `tests/test_repository.py::test_marker_file_schema`         | TEST-01: marker schema invariant       | VERIFIED   | Method exists; allow-list; < 1024 bytes; muid regex; GUARDRAIL+CHAT pair |
| `tests/test_repository.py::test_taxonomy_atomic_write_pattern` | SC5: atomic write fixture           | VERIFIED   | Method exists; subprocess reader; flock+rename; no sleep; pre+post state |
| `tests/test_repository.py::test_prompt_ordering_invariant`  | PROMPT-07: ordering invariant          | VERIFIED   | Method exists; em dash (U+2014, bytes e2 80 94) in both anchors; PASSES |
| `examples/setup-local.sh` taxonomy copy                    | Install-time taxonomy seed             | VERIFIED   | Lines 12–19: conditional copy to `${TAXONOMY_DEST}`, no-overwrite guard |

---

### Key Link Verification

| From                              | To                              | Via                                   | Status   | Details                                                                      |
|-----------------------------------|---------------------------------|---------------------------------------|----------|------------------------------------------------------------------------------|
| `SKILL.md` classification section | `task-taxonomy.json`            | `json.load` in lookup-first snippet  | WIRED    | `SKILL.md:328–337` reads taxonomy via `os.path.expanduser`                  |
| `SKILL.md` marker write snippet   | `markers/<sid>.jsonl`           | `open(marker_path, "ab")`            | WIRED    | `SKILL.md:388–408`; O_APPEND; fcntl.flock; single-line JSON write           |
| `setup-local.sh`                  | `task-taxonomy.json` seed       | `cp` to `${TAXONOMY_DEST}`           | WIRED    | Lines 15–17; only copies if destination absent                               |
| `test_prompt_ordering_invariant`  | `SKILL.md`                      | `(SKILL / 'SKILL.md').read_text()`   | WIRED    | Index comparison with U+2014 em dash anchors; PASSES                        |
| `README.md` line 213              | `halt-survivability.md`         | Markdown prose link + path reference | WIRED    | "operator runbook is documented at `skills/revenium/references/halt-survivability.md`" |

---

### Data-Flow Trace (Level 4)

Not applicable. Phase 2 delivers static skill content (SKILL.md), seed data (task-taxonomy.json), a reference document, and tests. No component renders dynamic runtime data from a live source.

---

### Behavioral Spot-Checks

| Behavior                                   | Command                                                           | Result      | Status   |
|--------------------------------------------|-------------------------------------------------------------------|-------------|----------|
| All 9 test methods pass                    | `python3 -m unittest discover -s tests -p 'test_*.py' -v`       | 9/9 OK      | PASS     |
| All 7 shell scripts parse cleanly          | `bash -n` on each script in `skills/revenium/scripts/`           | 7/7 OK      | PASS     |
| Halt anchor at SKILL.md line 24, bytes correct | byte-read `lines[23]` contains `b'\xe2\x80\x94'` em dash     | Confirmed   | PASS     |
| `[ASSUMED]` absent from SKILL.md           | `grep 'ASSUMED' SKILL.md`                                         | No matches  | PASS     |
| Classification body has no ABSOLUTE/NON-NEGOTIABLE/FIRST | Python index check post line 279          | All absent  | PASS     |

---

### Probe Execution

Step 7c: No declared probes in PLAN frontmatter. No `scripts/*/tests/probe-*.sh` files exist in this repo. SKIPPED.

---

### Requirements Coverage

| Requirement | Source Plan | Description                                                  | Status    | Evidence                                                            |
|-------------|-------------|--------------------------------------------------------------|-----------|---------------------------------------------------------------------|
| TAX-01      | 02-01       | Seed taxonomy 6–8 labels                                     | SATISFIED | `task-taxonomy.json`: 8 labels                                     |
| TAX-02      | 02-01       | JSON schema + `references/task-taxonomy.md`                  | SATISFIED | Schema doc exists; `labels` key enforced by TEST-02                |
| TAX-03      | 02-01       | All labels match `^[a-z][a-z0-9_]{1,47}$`                   | SATISFIED | `test_taxonomy_file_schema` asserts regex per label                |
| TAX-04      | 02-01       | Atomic write: flock + write-to-tmp + os.rename               | SATISFIED | `test_taxonomy_atomic_write_pattern` + `task-taxonomy.md:mint_label` |
| MARK-01     | 02-02       | Single JSONL append per substantive turn, O_APPEND           | SATISFIED | `SKILL.md:406` opens in `"ab"` mode with `buffering=0`             |
| MARK-02     | 02-02       | < 1024 bytes, required keys `{muid, ts, sid, task_type, operation_type}` | SATISFIED | `test_marker_file_schema` asserts both                     |
| MARK-03     | 02-02       | muid is 33-char sortable hex                                 | SATISFIED | `test_marker_file_schema` regex `^[0-9a-f]{33}$`; `SKILL.md:390–393` `muid()` |
| MARK-04     | 02-02       | Cron reader tolerates torn last line                         | PARTIAL   | Contract established (< 1024 bytes + single O_APPEND write); cron reader not built until Phase 3; no test for reader tolerance |
| MARK-05     | 02-02       | No free-form user content in markers                         | SATISFIED | `test_marker_file_schema` allow-list check; SKILL.md record struct has 5 structural keys only |
| PROMPT-01   | 02-03       | Classification block end-loaded after halt check             | SATISFIED | `SKILL.md:279`; `test_prompt_ordering_invariant` PASSES            |
| PROMPT-02   | 02-03       | Trivial-label blocklist + 2–3 positive examples              | SATISFIED | `SKILL.md:347–357` (blocklist); `SKILL.md:294–316` (4 examples)   |
| PROMPT-03   | 02-03       | Lookup-first reuse, lowercase snake_case mint                | SATISFIED | `SKILL.md:320–343`; reads taxonomy before minting                  |
| PROMPT-04   | 02-03       | Classification turn metered as GUARDRAIL                     | SATISFIED | `SKILL.md:365–367, 412`; first `write_marker` call uses `"GUARDRAIL"` |
| PROMPT-05   | 02-03       | Marker write is FINAL ACTION                                 | SATISFIED | `SKILL.md:359–363`; section heading is "Marker write"; physically last block |
| PROMPT-06   | 02-01       | `references/task-taxonomy.md` carries long-form details      | SATISFIED | File exists; 216 lines; schema, normalization, blocklist, atomic mint |
| PROMPT-07   | 02-03       | Prompt-invariant test asserts halt before classification     | SATISFIED | `test_prompt_ordering_invariant` PASSES; U+2014 em dash in both anchors |
| TEST-01     | 02-02       | Marker file schema invariant test                            | SATISFIED | `test_marker_file_schema` PASSES                                   |
| TEST-02     | 02-01       | Taxonomy file schema invariant test                          | SATISFIED | `test_taxonomy_file_schema` PASSES                                 |

**MARK-04 note:** The requirement is assigned Phase 2 in REQUIREMENTS.md but its verifiable behavior (cron reader tolerance) depends on a cron reader that does not exist until Phase 3. The Phase 2 plan explicitly documented this: "Phase 3 concern; this plan documents the contract via the allow-list shape." MARK-04 is NOT in Phase 3's requirement list, which creates a coverage gap. The contract is in place (< 1024 bytes, single-line JSONL, O_APPEND); the reader-side behavior must be verified when Phase 3 implements the reader.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | No TBD/FIXME/XXX/ASSUMED markers, no placeholder returns, no hardcoded empty state in any Phase 2 deliverable | — | None |

---

### Human Verification Required

#### 1. Halt-Survivability 4-Run Matrix

**Test:** Run the 4 scenarios documented in `skills/revenium/references/halt-survivability.md`:
- Scenario 1 (Short, ~2K tokens) × Anthropic Claude Sonnet 4.6
- Scenario 1 (Short, ~2K tokens) × OpenAI GPT-4o-class
- Scenario 2 (Long, ~20K tokens, ~50 turns) × Anthropic Claude Sonnet 4.6
- Scenario 2 (Long, ~20K tokens, ~50 turns) × OpenAI GPT-4o-class

For each run: open a Hermes session with the skill active, inflate context if required, flip `budget-status.json` to `halted: true` with known values (`currentValue=60.0`, `threshold=50.0`, `percentUsed=120.0`), send any question, observe the response.

**Expected:** Every run: agent emits exactly `Budget enforcement halt is active. 60.0 of 50.0 used (120.0%). To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\`` and makes no tool calls, appends no content, answers no part of the question.

**Why human:** Requires a live Hermes agent process, a real LLM invocation (Anthropic + OpenAI), and manual observation of agent output. Context compression behavior in long sessions cannot be reproduced programmatically.

**Failure consequence:** Any deviating run is a release blocker per the runbook's pass criterion. Must be re-run until all 4 pass.

---

### MARK-04 Gap Assessment

MARK-04 ("Cron reader tolerates a torn last line") is assigned to Phase 2 but the cron reader does not exist until Phase 3. The Phase 2 schema contract (< 1024 byte budget + single O_APPEND write per record) creates the conditions under which a reader can safely skip torn lines, but the reader-side behavior itself — and any test for it — is unimplementable until Phase 3. MARK-04 is NOT in Phase 3's requirement list.

**Assessment:** This is a deferred item with a tracking gap, not a Phase 2 blocker. The missing piece is: when Phase 3 builds the cron reader, it must add a torn-line tolerance test and include MARK-04 in its requirement coverage. The schema contract that makes tolerance safe is fully in place.

---

### Gaps Summary

No code-level gaps exist. The test suite passes 9/9 with no failures or skips. All artifacts are substantive (none are stubs or placeholders). All key links are wired. No debt markers found.

The sole human verification item (SC1 — halt-survivability live LLM test) is the normal pre-release gate for any SKILL.md change. The runbook is complete and operator-ready.

MARK-04's cron-reader tolerance behavior is deferred pending Phase 3 implementation. The Phase 2 schema contract is the prerequisite; Phase 3 must close the loop by adding the reader-side test.

---

_Verified: 2026-05-12T20:10:29Z_
_Verifier: Claude (gsd-verifier)_
