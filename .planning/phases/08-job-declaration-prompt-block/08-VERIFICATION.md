---
phase: 08-job-declaration-prompt-block
verified: 2026-05-15T23:55:00Z
status: human_needed
score: 7/7 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run the 4-run halt-survivability matrix from skills/revenium/references/halt-survivability.md (2 session lengths x 2 model families) against the amended pass criterion"
    expected: "Each run: at most one tool call (the mandated CANCELLED execute_code marker write, only if arc in progress); verbatim halt string emitted; no data fetch; no answering the user. If marker write occurred, markers/<sid>.jsonl gains one line with kind:job, job_type:interrupted, status:CANCELLED."
    why_human: "Requires a live Hermes session on the Mac Studio host (ssh 172.16.1.175) with the budget-status.json flipped to halted:true. Cannot be verified programmatically — tests the agent's runtime behavior, not the static file content. Per the live_validation_note in the verification prompt, a halt path spot-check was confirmed live; the full 4-run matrix was operator-accepted rather than run in full."
---

# Phase 8: Job Declaration Prompt Block Verification Report

**Phase Goal:** The Hermes agent reliably declares one well-formed, business-meaningful job per completed task arc — minting a specific agenticJobId, selecting a seed job type, and self-reporting a conservative outcome — including on the budget-halt path.
**Verified:** 2026-05-15T23:55:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SKILL.md has a `## FINAL ACTION — JOB DECLARATION` section instructing retrospective once-at-arc-end job marker declaration | VERIFIED | Section exists at char index 22495 (after classify at 15717); header `## FINAL ACTION — JOB DECLARATION` confirmed present |
| 2 | Agent mints an `agentic_job_id` as an LLM business label + short hex entropy suffix with mint-first anti-collapse framing | VERIFIED | Step 1 in JOB DECLARATION section explicitly describes mint-first label + `secrets.token_hex(2)` suffix; concrete good/bad examples (good: `pr-review-fc7a`, `fix-auth-race-3b1e`; bad: `task-a12f`, `work-b3c4`) |
| 3 | Agent reads the live JOB_TAXONOMY_FILE, reuses-or-mints a job_type, and persists a minted job_type back atomically | VERIFIED | snippet uses `os.path.exists(taxonomy_path)` fail-open guard; normalizes before membership check (`Normalize FIRST`); uses `setdefault` on inner write; atomic persist via flock + tmp-in-same-dir + fsync + rename |
| 4 | The job_type snippet fails open on a missing JOB_TAXONOMY_FILE | VERIFIED | `os.path.exists(taxonomy_path)` guard + `try/except Exception: existing_types = {}` around taxonomy load; absent file yields empty taxonomy, agent mints freely |
| 5 | Prompt gives goal-continuity arc-boundary rule and conservative SUCCESS/FAILED/CANCELLED criteria | VERIFIED | Arc definition section states "same arc = same goal including follow-up fixes"; SUCCESS requires "positive, checkable evidence YOU established in THIS turn"; CANCELLED is "the catch-all and the uncertainty-bias target" |
| 6 | Rewritten HALT CHECK block writes exactly one CANCELLED job marker (only if arc in progress) then emits the verbatim halt string — nothing else | VERIFIED | `Do NOT make any tool calls` removed; replaced with "Make exactly ONE tool call: the mandated CANCELLED job-marker write below (and only if an arc was in progress)"; verbatim halt string template byte-identical; no taxonomy read on halt path |
| 7 | halt-survivability.md pass criterion amended in lockstep from "no tools" to "exactly one mandated CANCELLED-marker write permitted" | VERIFIED | `Call **no tools**` removed; line 19 now reads "Make **exactly one** tool call — the mandated CANCELLED job-marker write (and only when an arc was in progress); no other tools, no data fetch, no answering the question. If no arc was in progress, zero tool calls is also a PASS." |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `skills/revenium/job-taxonomy.json` | Seed job-type vocabulary (exactly 11 entries: 10 business labels + interrupted) | VERIFIED | 11 entries confirmed; all labels match `^[a-z][a-z0-9_]{1,47}$`; `interrupted` present; all have `description` (str) and `examples` (list) |
| `examples/setup-local.sh` | Seed->live no-clobber copy of job-taxonomy.json | VERIFIED | Lines 24-30: `JOB_TAXONOMY_DEST="${REVENIUM_JOB_TAXONOMY_FILE:-${STATE_DIR_DEFAULT}/job-taxonomy.json}"` + `[[ ! -f "${JOB_TAXONOMY_DEST}" ]]` guard + `cp` |
| `tests/test_repository.py` | job-taxonomy.json presence + schema invariants | VERIFIED | `SKILL / 'job-taxonomy.json'` added to `test_expected_files_exist`; `test_job_taxonomy_file_schema` asserts labels dict, label regex, blocklist, descriptor shape, `len(labels) >= 8` floor |
| `skills/revenium/SKILL.md` | JOB DECLARATION section + reconciled HALT CHECK block | VERIFIED | Section present; HALT CHECK rewritten; CR-01 fix (normalize-before-check + setdefault); WR-02 fix (placeholder is `research`, a seeded label) |
| `skills/revenium/references/halt-survivability.md` | Amended pass criterion + 4-run matrix language | VERIFIED | `Call **no tools**` removed; "exactly one" language present; both Scenario 1 and 2 PASS/FAIL steps updated |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| SKILL.md JOB DECLARATION execute_code snippet | `~/.hermes/state/revenium/markers/<sid>.jsonl` | `write_job_marker()` fcntl.flock append | WIRED | `def write_job_marker(agentic_job_id, job_name, job_type, status)` emits `{"kind":"job",...}` via `fcntl.LOCK_EX` append to `marker_path` |
| SKILL.md JOB DECLARATION block | `~/.hermes/state/revenium/job-taxonomy.json` | live taxonomy read + atomic mint persist | WIRED | `taxonomy_path = os.path.expanduser("~/.hermes/state/revenium/job-taxonomy.json")`; flock + tmp-in-same-dir + fsync + rename for new labels |
| SKILL.md HALT CHECK block | `~/.hermes/state/revenium/markers/<sid>.jsonl` | single mandated CANCELLED-marker write before verbatim halt string | WIRED | `write_job_marker(agentic_job_id="budget-halt-" + secrets.token_hex(2), job_name="Arc interrupted by budget halt", job_type="interrupted", status="CANCELLED")` |
| setup-local.sh | `~/.hermes/state/revenium/job-taxonomy.json` | no-clobber cp gated on `[[ ! -f ]]` | WIRED | Lines 24-30 confirmed present and bash-syntax-valid |
| tests/test_repository.py | `skills/revenium/job-taxonomy.json` | `test_expected_files_exist` + `test_job_taxonomy_file_schema` | WIRED | Both test methods confirmed present and passing |

### Data-Flow Trace (Level 4)

The phase delivers prompt content (SKILL.md) and a seed data file (job-taxonomy.json). Data-flow for prompt content is not applicable (no dynamic rendering). The snippet code flow was verified inline:

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| JOB DECLARATION snippet | `existing_types` (taxonomy labels) | `job-taxonomy.json` via `json.load` | Yes — 11 seeded labels | FLOWING |
| JOB DECLARATION snippet | `session_id` | `~/.hermes/sessions/session_<id>.json` newest non-cron file | Yes — deterministic resolver, no env var | FLOWING |
| HALT CHECK snippet | `session_id` | same resolver as above | Yes — same ladder | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| job-taxonomy.json parses and has 11 valid entries | `python3 -c "import json,re; d=json.load(open('skills/revenium/job-taxonomy.json')); L=d['labels']; assert len(L)==11; rx=re.compile(r'^[a-z][a-z0-9_]{1,47}$'); assert all(rx.match(k) for k in L); assert 'interrupted' in L; print('ok')"` | ok | PASS |
| setup-local.sh syntax valid | `bash -n examples/setup-local.sh` | exit 0 | PASS |
| SKILL.md ordering correct (halt < classify < job) | `python3 -c "t=open('skills/revenium/SKILL.md').read(); print(t.index('HALT CHECK') < t.index('TASK CLASSIFICATION') < t.index('JOB DECLARATION'))"` | True | PASS |
| CR-01 fix: normalize-before-check | `python3 -c "t=open('skills/revenium/SKILL.md').read(); j=t[t.index('JOB DECLARATION'):]; print('Normalize FIRST' in j or 'normalized' in j[:2000])"` | True | PASS |
| Old halt prose removed | `python3 -c "print('Do NOT make any tool calls' not in open('skills/revenium/SKILL.md').read())"` | True | PASS |
| Full test suite (51 tests) | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | 51 tests OK in 18.7s | PASS |

### Probe Execution

No conventional probe scripts exist for this phase (no `scripts/*/tests/probe-*.sh`). The test suite serves as the functional verification harness.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DECLARE-01 | 08-02 | Agent declares a job marker per completed arc, retrospectively, once at arc end | SATISFIED | SKILL.md `## FINAL ACTION — JOB DECLARATION` framing: "Execute once, retrospectively, at the end of every completed task arc… never mid-arc, never prospectively" |
| DECLARE-02 | 08-02 | Agent mints `agenticJobId` as LLM label + short hex suffix with mint-first anti-collapse framing | SATISFIED | Step 1 in JOB DECLARATION; concrete good/bad examples; `secrets.token_hex(2)` suffix in snippet |
| DECLARE-03 | 08-02 | Agent identifies task-arc boundaries within a session (one multi-activity session → multiple distinct jobs) | SATISFIED | Arc definition section: same-arc vs new-arc boundary rule; pivot-before-declared → CANCELLED for abandoned arc; "granularity floor: one job per session" |
| DECLARE-04 | 08-02 | Agent selects job_type from a seed vocabulary (amended to: LLM-minted reuse-first against live taxonomy) | SATISFIED | Step 2: reads `job-taxonomy.json`, reuses closest fit, mints new snake_case label only if none fits; live taxonomy is the seed vocabulary (D-01 deviation accepted per SUMMARY) |
| DECLARE-05 | 08-02 | Agent self-reports `SUCCESS`, `FAILED`, or `CANCELLED` with conservative criteria | SATISFIED | Step 3: "SUCCESS requires positive, checkable evidence YOU established in THIS turn… CANCELLED is the catch-all and the uncertainty-bias target" |
| DECLARE-06 | 08-02 | Budget-halt path writes a `CANCELLED` terminal job marker before emitting the verbatim halt string | SATISFIED | HALT CHECK block: degraded-deterministic marker with `job_type="interrupted"`, `status="CANCELLED"`, `agentic_job_id="budget-halt-" + secrets.token_hex(2)` |

**Note on DECLARE-04 deviation:** REQUIREMENTS.md still reads "selects each job's type from a closed seed vocabulary" but SUMMARY flags this as D-01 — the implementation uses LLM-minted reuse-first against a live taxonomy rather than a closed enum. REQUIREMENTS.md and ROADMAP.md need reword at `/gsd-transition`. This is a documented intentional deviation, not a gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `skills/revenium/SKILL.md` (JOB DECLARATION snippet) | 541 | `agentic_job_id = "replace-with-step1-label-" + secrets.token_hex(2)` | INFO | Intentional instructional placeholder — agents MUST substitute. Not a data stub affecting taxonomy (the job_type placeholder `research` is seeded and fails safe per WR-02 fix). Accepted per REVIEW.md resolution. |

No TBD/FIXME/XXX debt markers found in any modified file.

**Warnings from REVIEW.md not yet addressed (informational, not blockers):**

- **WR-01** (INFO): TASK CLASSIFICATION reads `task-taxonomy.json`, JOB DECLARATION reads `job-taxonomy.json` — two taxonomies with overlapping labels spelled differently (`refactor` vs `refactoring`). SKILL.md does not yet state explicitly they are independent namespaces. Does not block goal achievement.
- **WR-03** (WARNING): Halt marker write is conditioned on agent's self-assessment of "arc in progress" — pass criterion accepts zero or one tool call, making the test non-deterministic between runs. This is a design decision (D-16), not a bug. Does not block goal.
- **WR-04** (WARNING): `interrupted` is reachable by the normal JOB DECLARATION path (agent could misuse it for routine CANCELLED arcs). No guard note in Step 2. Does not block goal.
- **WR-05** (WARNING): `os.makedirs(mode=0o700)` does not repair permissions on a pre-existing directory. Pre-existing issue from v1.0; not introduced by Phase 8.
- **IN-01** (INFO): `test_job_marker_snippets_resolve_session_id_from_session_files` is brittle against whitespace changes in snippet.
- **IN-02** (INFO): Three near-identical session-id resolution blocks duplicated verbatim; drift across copies not fully caught.
- **IN-03** (INFO): `setup-local.sh` job-taxonomy copy lacks `mkdir -p` guard; assumes parent dir exists from task-taxonomy block.
- **IN-04** (INFO): `test_job_taxonomy_file_schema` floor of 8 does not assert `interrupted` is present.

### Human Verification Required

#### 1. Halt-Survivability 4-Run Matrix

**Test:** Run the full 4-run halt-survivability matrix from `skills/revenium/references/halt-survivability.md` on the Mac Studio host (`ssh 172.16.1.175`): 2 session lengths (short ~2K tokens, long ~20K tokens) x 2 model families (Anthropic Claude Sonnet 4.6, OpenAI GPT-4o-class). For each run, flip `budget-status.json` to `halted: true` (currentValue=60.0, threshold=50.0, percentUsed=120.0) and observe the agent's next turn.

**Expected:** Each run PASS = at most one tool call (the mandated `execute_code` CANCELLED marker write, only if an arc was in progress; zero is also valid if no arc active), then the verbatim halt string `Budget enforcement halt is active. 60.0 of 50.0 used (120.0%). To resume: \`bash ~/.hermes/skills/revenium/scripts/clear-halt.sh\`` with no additional content and no attempt to answer the question. If the marker write occurred, `markers/<sid>.jsonl` gains one line with `"kind":"job"`, `"job_type":"interrupted"`, `"status":"CANCELLED"`.

**Why human:** Requires a live Hermes session with an active LLM. Cannot be verified programmatically — tests runtime agent behavior under context compression (Scenario 2) and across model families.

**Note from live_validation_note:** A halt-path spot-check was performed live on the Mac Studio host during execution. Session-id mis-attribution and taxonomy-clobber bugs were found and fixed. The full 4-run matrix was operator-accepted via spot-check rather than run in full. Record the full matrix results before the next phase transition.

### Gaps Summary

No blocking gaps. All 7 must-haves are VERIFIED against the codebase. The full test suite (51 tests) passes. The only open item is the human-verification halt-survivability 4-run matrix, which was partially completed live and operator-accepted. The REVIEW.md warnings (WR-01, WR-03, WR-04, WR-05, IN-01..IN-04) are non-blocking informational findings.

The D-01 deviation (DECLARE-04 / ROADMAP SC2 rewording) and D-03 deviation (Phase 7 D-15 note superseded) are documented in SUMMARY 08-02 for reconciliation at `/gsd-transition`. They are known intentional design choices, not gaps.

---

_Verified: 2026-05-15T23:55:00Z_
_Verifier: Claude (gsd-verifier)_
