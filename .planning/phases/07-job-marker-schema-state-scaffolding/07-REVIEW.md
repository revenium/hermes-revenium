---
phase: 07-job-marker-schema-state-scaffolding
reviewed: 2026-05-15T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - skills/revenium/scripts/common.sh
  - skills/revenium/scripts/hermes-report.sh
  - tests/test_repository.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-05-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Phase 7 adds job-marker schema scaffolding: two new path declarations in `common.sh`
(`JOBS_LEDGER_FILE`, `JOB_TAXONOMY_FILE`), a `kind`-aware branch in the `hermes-report.sh`
marker-reader Python heredoc, a `touch` of the new jobs ledger, and two new tests.

The change is well-commented and the test for argv byte-identity (`SCHEMA-04`) is a
genuinely strong regression guard. However, the new `kind = m.get("kind")` call
introduces a real **behavior regression** for non-object JSONL lines: it now raises an
uncaught `AttributeError` that escapes the heredoc's per-line `try/except` and the
file-read `try` block, causing the whole session to lose marker attribution. The
pre-existing code skipped a JSON-array line silently. This is the most important
finding. Two further warnings concern an unbounded `jobs_by_id` collector and a
non-validating `agentic_job_id` used as a dict key. The new test suite, while solid on
argv identity, does not exercise any of these malformed-input paths.

## Warnings

### WR-01: `kind = m.get("kind")` regresses handling of non-object JSONL lines

**File:** `skills/revenium/scripts/hermes-report.sh:409`
**Issue:** `m.get("kind")` is now the first attribute access performed on a freshly
`json.loads`-ed marker line. If a line is valid JSON but not a JSON object — e.g.
`[1,2,3]`, `"hello"`, `42`, `null`, `true` — `m` is a list/str/int/NoneType/bool and
`.get` raises `AttributeError`. The per-line `try/except` at lines 401-404 only catches
`json.JSONDecodeError`, and the surrounding file-read `try` at line 390 only catches
`OSError` (line 444). `AttributeError` is neither, so it escapes the `for` loop, exits
the heredoc non-zero, triggers `|| marker_output=""` (line 469), and the session falls
through to legacy `unclassified` metering with a `marker-read fall-through` warn.

This is a regression: pre-edit, the first access was
`all(k in m for k in REQUIRED_KEYS)`. For a JSON-array line, `'muid' in [1,2,3]`
returns `False` with no exception, so that one line was skipped and the remaining
valid task markers were still processed. Now a single malformed non-object line
anywhere in `<sid>.jsonl` discards attribution for the *entire* session. The D-06
comment claims "absent kind falls through ... unchanged" but that guarantee only
holds for JSON *objects*.

**Fix:** Guard for dict before calling `.get`, consistent with the soft-fail
"skip the line, keep going" contract documented for MARK-04 / D-15:
```python
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # A valid-JSON but non-object line (array/scalar) is not a marker.
                if not isinstance(m, dict):
                    continue
                kind = m.get("kind")
```

### WR-02: `jobs_by_id` collector is unbounded — no cap on job-marker count or size

**File:** `skills/revenium/scripts/hermes-report.sh:383,413,467`
**Issue:** The task-marker path has an explicit per-line 4 KB memory cap
(line 397-398, "T-03-04 defense"). The new job path has no equivalent bound:
`jobs_by_id` grows one entry per accepted `kind:"job"` line with no cap on entry
count, and the 4 KB per-line cap is the only limit on each entry's size. A marker
file with thousands of job lines is held entirely in memory and then fully
serialized into the single `JOBS_JSON=` stdout line, which bash captures into
`marker_output` and re-scans with five `sed` passes (lines 472-484). The task-marker
side at least feeds a bounded downstream; the job side accumulates without limit
into a value that is currently unused (`jobs_json` is captured then discarded).
For scaffolding this is latent, but the asymmetry with the documented task-side
cap is a defect waiting for Phase 9 to consume it.

**Fix:** Apply a count cap mirroring the per-line cap, e.g. stop collecting after
N job markers and log a warn, or document explicitly why no cap is needed:
```python
JOB_MARKER_CAP = 1000
...
                if kind == "job":
                    if len(jobs_by_id) >= JOB_MARKER_CAP:
                        continue
                    if all(k in m for k in JOB_REQUIRED):
                        jobs_by_id[m["agentic_job_id"]] = m
                    continue
```

### WR-03: `agentic_job_id` is used as a dict key with no type/shape validation

**File:** `skills/revenium/scripts/hermes-report.sh:412-413`
**Issue:** `jobs_by_id[m["agentic_job_id"]] = m` keys the collector on the raw
JSON value of `agentic_job_id`. `JOB_REQUIRED` membership only checks the key is
*present* (`all(k in m for k in JOB_REQUIRED)`) — it does not check the value is a
non-empty string. JSON permits `agentic_job_id` to be `null`, a number, a bool, or
even a list/dict. A list or dict value raises `TypeError: unhashable type` on the
assignment — and like WR-01, that `TypeError` is uncaught by the `JSONDecodeError`
and `OSError` handlers, so it escapes and discards the whole session's attribution.
A `null` or numeric value is silently accepted as a key, which will later collide
or mis-group in Phase 9. The `sid` field, by contrast, has an upstream A2
assertion (`':' not in sid`) in `parse_prior_state`; `agentic_job_id` has no
analogous guard despite being load-bearing for the D-12 "last line wins" semantics.

**Fix:** Validate the key is a non-empty string before using it:
```python
                if kind == "job":
                    job_id = m.get("agentic_job_id")
                    if not isinstance(job_id, str) or not job_id:
                        continue
                    if all(k in m for k in JOB_REQUIRED):
                        jobs_by_id[job_id] = m
                    continue
```

## Info

### IN-01: New tests do not cover the malformed-job-marker paths

**File:** `tests/test_repository.py:3469-3760`
**Issue:** `test_job_marker_does_not_alter_task_completion_argv` only feeds
*well-formed* canonical job markers. None of the failure modes in WR-01/WR-02/WR-03
(non-object JSONL line, unhashable `agentic_job_id`, missing `JOB_REQUIRED` keys,
job marker with `kind:"job"` but bad value types) are exercised. The phase brief
emphasizes byte-identity and forward-compat, but the regression-prevention value of
the suite is limited without a malformed-input case proving valid task markers
still meter when a bad job line is present.
**Fix:** Add a sub-case that appends a non-object line (`[1,2,3]`) and a
missing-key job line to the marker file and asserts the 2 task-marker invocations
still occur unchanged.

### IN-02: `JOB_TAXONOMY_FILE` is declared but never referenced or created

**File:** `skills/revenium/scripts/common.sh:25`
**Issue:** `JOBS_LEDGER_FILE` is at least `touch`ed in `hermes-report.sh:35`.
`JOB_TAXONOMY_FILE` is declared in `common.sh` but is referenced by no script and
never created. It is dead scaffolding for this phase. This is acceptable as
forward-compat per the D-13 comment, but a declared-and-unused path is easy to
drift (e.g. a typo in the path would not be caught until Phase 9). Consider a
test asserting the variable name only, or defer the declaration to the phase that
consumes it.
**Fix:** Either keep (intentional scaffolding, acceptable) or move the
declaration to the consuming phase to avoid a long-lived unused path.

### IN-03: `jobs_json` local is captured then discarded

**File:** `skills/revenium/scripts/hermes-report.sh:482-484`
**Issue:** `local jobs_json` is assigned from `sed -n 's/^JOBS_JSON=//p'` and never
read — the inline comment ("intentionally unused here ... for Phase 9 consumption")
acknowledges this. An assigned-but-unused variable is dead code today. Under
`set -uo pipefail` it is harmless, but it adds a `sed` subprocess per session per
tick for a value that is thrown away.
**Fix:** Acceptable as documented scaffolding; alternatively drop the capture
until Phase 9 actually consumes `JOBS_JSON=` and add it back then, avoiding a
per-session `echo | sed` for an unused value.

### IN-04: `argv_to_flags` test helper mis-parses negative-number flag values

**File:** `tests/test_repository.py:3520-3534`
**Issue:** `argv_to_flags` treats any token starting with `--` as a flag and the
next token as its value *only if* that next token does not itself start with `--`.
A flag value that begins with `-` but not `--` is fine, but a negative number is
not a current risk here. The real fragility: a boolean flag followed by another
`--flag` is handled, but a flag whose legitimate value happens to start with `--`
(unlikely for this argv but not impossible for `--environment` or `--agent` values)
would be misclassified as a bare boolean. For the Phase 7 fixtures this does not
fire, so it is informational only.
**Fix:** None required for current fixtures; note the helper assumes no flag value
starts with `--`. If future fixtures use such values, parse against a known flag
set instead.

---

_Reviewed: 2026-05-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
