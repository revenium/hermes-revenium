---
phase: 08-job-declaration-prompt-block
reviewed: 2026-05-15T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - examples/setup-local.sh
  - skills/revenium/job-taxonomy.json
  - skills/revenium/references/halt-survivability.md
  - skills/revenium/SKILL.md
  - tests/test_repository.py
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-05-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Phase 8 adds the `FINAL ACTION — JOB DECLARATION` section to `SKILL.md`, reconciles
the `HALT CHECK` block with a `CANCELLED` job-marker write, ships a seed
`job-taxonomy.json`, wires its seed→live copy into `examples/setup-local.sh`, and
extends `tests/test_repository.py` with job-taxonomy schema and prompt-ordering
invariants.

The wire-protocol shape (marker record, atomic taxonomy persist) is broadly sound and
the session-id resolution change is in-scope per the review brief. However, the
JOB DECLARATION `execute_code` snippet contains a **taxonomy data-loss bug**: a
newly-minted `job_type` that normalizes onto an *existing* seed label silently
overwrites that label's description and examples, because the de-duplication check
runs against the un-normalized agent input. There are also several robustness and
consistency gaps that weaken the feature's central goal — a non-fragmented taxonomy.

## Critical Issues

### CR-01: JOB DECLARATION snippet overwrites existing taxonomy labels on normalization collision

**File:** `skills/revenium/SKILL.md:556-576`
**Issue:** The taxonomy persist block decides whether `job_type` is "newly minted"
*before* normalization, then writes under the *post-normalization* key:

```python
if job_type not in existing_types:        # checks RAW agent value
    normalized = re.sub(...)              # e.g. "Bug Fix" -> "bug_fix"
    if re.match(r'^[a-z][a-z0-9_]{1,47}$', normalized):
        job_type = normalized             # job_type now == "bug_fix"
        ...
        data.setdefault("labels", {})[job_type] = {   # OVERWRITES seeded "bug_fix"
            "description": job_name,
            "examples": [],
        }
```

If the agent supplies a `job_type` whose normalized form equals an already-seeded
label — e.g. `"Bug Fix"`, `"bug-fix"`, `"Code Review"`, `"DevOps"` — the raw value
is absent from `existing_types`, so the block is entered. After normalization the
key collides with the seed entry (`bug_fix`, `code_review`, `devops`, ...), and
`data["labels"][job_type] = {...}` **replaces the curated description and examples
with the arc's `job_name` and an empty examples list**. This is permanent
destruction of the shipped taxonomy content for every install that hits the path —
and it directly defeats the phase's stated core value (a stable, non-fragmented
taxonomy). Casing/hyphenation variants from an LLM agent are not an edge case; they
are the expected failure mode the normalization step exists to absorb.

**Fix:** Normalize first, then perform the membership check against the normalized
value, and only write when the normalized key is genuinely absent:

```python
if job_type not in existing_types:
    normalized = re.sub(r'[^a-z0-9_]', '', re.sub(r'[-\s]+', '_', job_type.lower()))
    if re.match(r'^[a-z][a-z0-9_]{1,47}$', normalized):
        job_type = normalized
        # Re-check AFTER normalization: a normalized collision with an existing
        # label is a reuse, not a mint — never overwrite a curated entry.
        if job_type not in existing_types:
            try:
                ...
                data.setdefault("labels", {}).setdefault(job_type, {
                    "description": job_name,
                    "examples": [],
                })
                ...
```

Using `setdefault` on the inner write is also a cheap belt-and-suspenders guard
against the same overwrite if `existing_types` was stale.

## Warnings

### WR-01: TASK CLASSIFICATION still points at `task-taxonomy.json` while JOB DECLARATION points at `job-taxonomy.json` — two taxonomies, no cross-reference

**File:** `skills/revenium/SKILL.md:354-365` vs `:483-487`
**Issue:** The TASK CLASSIFICATION section reads `~/.hermes/state/revenium/task-taxonomy.json`
and the JOB DECLARATION section reads `~/.hermes/state/revenium/job-taxonomy.json`.
They are distinct controlled vocabularies with overlapping concepts (`code_review`
exists in both; `refactor` vs `refactoring`, `debugging` in both, `research` in
both). An agent reading both sections within one turn now has to keep two
similarly-named files straight, and the seed files use *different* label spellings
for the same concept (`refactor` in task-taxonomy per the test at line 152,
`refactoring` in job-taxonomy line 24). This is exactly the fragmentation the phase
brief warns is a feature failure. At minimum SKILL.md should explicitly state that
`task_type` and `job_type` are different namespaces and that the spelling mismatch
is intentional; better, align the overlapping labels.
**Fix:** Add one sentence to the JOB DECLARATION intro clarifying `job-taxonomy.json`
is a separate file from `task-taxonomy.json` and the two namespaces are independent,
or reconcile the shared labels (`refactor`/`refactoring`) to one spelling.

### WR-02: JOB DECLARATION snippet ships placeholder values that produce a valid-but-garbage marker if the agent forgets Step 1-3

**File:** `skills/revenium/SKILL.md:540-544`
**Issue:** The snippet hardcodes:

```python
agentic_job_id = "replace-with-step1-label-" + secrets.token_hex(2)
job_name = "Replace with a short human-readable description of the arc"
job_type = "replace_with_step2_type"
status = "CANCELLED"
```

If the agent runs the snippet without substituting (a realistic LLM failure mode
under context dilution — the exact scenario `halt-survivability.md` exists to guard
against), it writes a structurally-valid job marker carrying
`job_type="replace_with_step2_type"`. That label passes the
`^[a-z][a-z0-9_]{1,47}$` regex, so the persist block will *add it to the live
taxonomy*, permanently polluting the vocabulary with a placeholder. Unlike the
TASK CLASSIFICATION snippet (which uses a real example label `"code_review"` that
fails safe), the placeholder here fails dirty.
**Fix:** Use a real, intentionally-conservative default such as
`job_type = "interrupted"` (already seeded, terminal, harmless) and an
`agentic_job_id` example value, mirroring how the TASK CLASSIFICATION snippet uses
`"code_review"`. Alternatively add a guard: `if job_type.startswith("replace"): raise SystemExit("job_type not set")`.

### WR-03: HALT CHECK permits a tool call while the section claims "make ZERO/ONE tool call" — contract ambiguity with the survivability test

**File:** `skills/revenium/SKILL.md:37-46`, `references/halt-survivability.md:19,83-90`
**Issue:** The HALT CHECK block instructs the agent to decide *itself* whether "an
arc was in progress" and conditionally emit a marker write. The pass criterion in
`halt-survivability.md` accepts either zero or one tool call. This makes the test
non-deterministic: the same halt scenario can PASS with a marker write or PASS
without one, depending on the agent's self-assessment of "mid-arc". A test whose
pass set includes "agent did X" and "agent did not do X" cannot detect a regression
where the agent stops emitting the marker entirely. The "exactly one tool call"
halt-survivability guarantee — historically the strongest anchor in this skill — is
now weakened to "zero or one".
**Fix:** Either make the marker write unconditional on halt (always one tool call,
deterministic), or have the test fixture control whether an arc is in progress so
each run has a single expected outcome. Document which.

### WR-04: `interrupted` job_type is reachable by the normal JOB DECLARATION path, inviting misuse

**File:** `skills/revenium/job-taxonomy.json:73-79`, `skills/revenium/SKILL.md:483-485`
**Issue:** `interrupted` is documented in the seed as a "Terminal job type for an arc
that was cut short by a budget halt or an explicit user cancellation". The HALT
CHECK snippet correctly uses it. But the JOB DECLARATION Step 2 instruction tells
the agent to "Reuse the closest-fitting existing `job_type`" from the same file —
nothing stops an agent from selecting `interrupted` for an ordinary `CANCELLED`
arc, conflating budget-halt interruptions with routine user pivots. That muddies
the very analytics distinction the feature is meant to provide.
**Fix:** Either move `interrupted` out of `labels` into a separate reserved section
the JOB DECLARATION step does not scan, or add an explicit note in Step 2:
"Do not select `interrupted` — it is reserved for the budget-halt path."

### WR-05: `os.makedirs(markers_dir, mode=0o700)` does not repair permissions on a pre-existing directory

**File:** `skills/revenium/SKILL.md:74-75, 395-396, 523-524`
**Issue:** All three snippets call `os.makedirs(markers_dir, mode=0o700, exist_ok=True)`.
The `mode` argument is ignored when the leaf directory already exists, and it is
also subject to the process umask on creation. If `markers/` was previously created
by another code path (e.g. `setup-local.sh` / `prune-markers.sh`) with looser
permissions, the marker files — which record session activity — remain
world-readable. Markers are session-attribution data, not secrets, so this is a
hardening gap rather than a vulnerability, but the `0o700` intent is silently
defeated.
**Fix:** If 0700 is a real requirement, follow `makedirs` with an explicit
`os.chmod(markers_dir, 0o700)`; otherwise drop the `mode=` argument so the code does
not imply a guarantee it does not deliver.

## Info

### IN-01: `test_job_marker_snippets_resolve_session_id_from_session_files` is brittle against whitespace

**File:** `tests/test_repository.py:386-407` (approx)
**Issue:** The new test asserts substring presence of literals like
`'f.startswith("session_")'` and `'f.endswith(".json")'`. Any reflow of the snippet
(line wrapping the comprehension differently, swapping single/double quotes) would
fail the test without any behavioral change. The test couples to source formatting,
not behavior.
**Fix:** Acceptable for a prompt file that is intentionally frozen, but consider
asserting against a normalized (whitespace-stripped) copy of the block, or document
that the snippet text is contractually frozen.

### IN-02: Three near-identical session-id resolution blocks duplicated verbatim across SKILL.md

**File:** `skills/revenium/SKILL.md:51-72, 376-393, 504-521`
**Issue:** The ~22-line session-id resolution preamble is copy-pasted three times.
A future fix to the resolution logic must be applied in three places and the
`test_job_marker_snippets_...` test only checks two of them (it filters on
`def write_job_marker`, which the TASK CLASSIFICATION block at line 376 does not
contain — that one defines `write_marker`). Drift between the three copies would
not be fully caught.
**Fix:** Inherent to an LLM-executed prompt file (no shared module possible).
Mitigate by extending the test to assert the resolution preamble is byte-identical
across all three python blocks.

### IN-03: `setup-local.sh` job-taxonomy copy lacks the `mkdir -p` guard the task-taxonomy copy relies on

**File:** `examples/setup-local.sh:24-30`
**Issue:** The job-taxonomy block reuses `STATE_DIR_DEFAULT` and assumes the
directory already exists because the preceding task-taxonomy block ran
`mkdir -p "$(dirname "${TAXONOMY_DEST}")"` (line 16). This is correct *today* only
because both destinations share the same parent directory and the task block runs
first. If `REVENIUM_JOB_TAXONOMY_FILE` is ever overridden to a different directory,
the `cp` at line 26 fails. Under `set -euo pipefail` that aborts the whole script.
**Fix:** Add `mkdir -p "$(dirname "${JOB_TAXONOMY_DEST}")"` before the `cp`, matching
the task-taxonomy block's own guard.

### IN-04: `test_job_taxonomy_file_schema` floor of 8 labels does not pin `interrupted` presence

**File:** `tests/test_repository.py:163-181`
**Issue:** The HALT CHECK snippet hard-depends on `interrupted` existing in the seed
taxonomy (SKILL.md:87-94 comment: "job_type \"interrupted\" is seeded in
job-taxonomy.json — no mint needed"). The schema test only asserts `>= 8` labels and
generic regex conformance; it would still pass if `interrupted` were removed,
silently breaking the halt-path contract.
**Fix:** Add `self.assertIn('interrupted', labels, 'HALT CHECK snippet depends on the
seeded "interrupted" job_type')`.

---

_Reviewed: 2026-05-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
