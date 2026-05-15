---
phase: 05-housekeeping-compat-hardening
verified: 2026-05-15T02:05:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
human_verification_resolved:
  - test: "Run prune-markers.sh against a live marker corpus on Mac Studio (bash 3.2.57)"
    result: pass
    evidence: |
      Operator UAT 2026-05-15T02:04 on Mac Studio (`ssh 172.16.1.175`):
      - Marker dir: 26 files (none older than 30d at default retention)
      - TEST 1 (dry-run): scanned=26 kept=26 removed=0 — `info` log line landed
      - TEST 2 (live): scanned=26 kept=26 removed=0 — clean exit
      - TEST 3 (idempotent re-run): scanned=26 kept=26 removed=0
      - TEST 4 (REVENIUM_MARKER_RETENTION_DAYS=1 dry-run): correctly flagged 2 markers from 2026-05-13 (age 1.4 days) and kept 24 fresher; SCANNED=26 KEPT=24 REMOVED=2
      - All log lines tee'd to revenium-metering.log via info-helper as designed (D-29)
    note: |
      First UAT round revealed prune-markers.sh did NOT work on Mac Studio (bash 3.2). Root cause:
      `${VAR@Q}` parameter expansion (added in bash 4.4) is unsupported in macOS stock /bin/bash 3.2.57.
      Local dev worked because of Homebrew bash 5.2 on PATH.

      Fix landed in commit `bfa15e5` (`fix(05): prune-markers.sh bash 3.2 compat (WR-02) — replace
      ${VAR@Q} with env passthrough`). Replaced the heredoc parameter expansion with an env-var
      passthrough into a single-quoted heredoc (the pattern hermes-report.sh already uses). UAT re-run
      passed on Mac Studio after the fix deployed.

      Pre-existing related defect found: `skills/revenium/scripts/clear-halt.sh:17` uses the same
      `${BUDGET_STATUS_FILE@Q}` pattern and has been latent-broken on Mac Studio since shipped.
      Captured as deferred (DEFERRED-CLEAR-HALT-BASH-32) — not in Phase 5 scope; suggested as a
      v1.1 quick task.
  - test: "Verify prune-markers.sh does NOT crash when REVENIUM_MARKER_RETENTION_DAYS=0 is exported"
    result: pass
    evidence: |
      TEST 5 on Mac Studio: `REVENIUM_MARKER_RETENTION_DAYS=0 prune-markers.sh --dry-run` correctly
      flagged ALL 26 markers as stale (age=0 cutoff). Documented behavior matches CONTEXT.md D-27
      (env override) + D-29 (dry-run preview). Script does not crash; behavior is documented.
      Hardening (e.g., minimum N=1 validation) deferred to v1.1 (DEFERRED-RETENTION-MIN-VALIDATION).
---

# Phase 5: Housekeeping & Compat Hardening Verification Report

**Phase Goal:** Marker files do not grow unbounded on long-running hosts, the project's compat invariants are pinned by automated tests, and the frontmatter / legacy-branding / runtime-path guards continue to pass.
**Verified:** 2026-05-14
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: `prune-markers.sh` removes stale marker files and leaves fresh ones untouched; idempotent on repeated runs | VERIFIED | `test_prune_markers_dry_run_and_live` at line 3117 in `tests/test_repository.py` exercises all three sub-cases (dry-run preserve, live delete, idempotent re-run) against a fixture with old / fresh / orphan markers. Test passed in the full suite run (45 tests OK). The script file exists, is executable, passes `bash -n`. |
| 2 | SC2: Full test suite (45 tests) passes end-to-end including `test_skill_frontmatter_has_hermes_metadata`, `test_runtime_paths_are_hermes_native`, `test_no_legacy_branding_left`, `test_shell_scripts_have_valid_syntax` (COMPAT-04, TEST-05) | VERIFIED | `python3 -m unittest discover -s tests -p 'test_*.py' -v` output: `Ran 45 tests in 14.731s — OK`. Baseline was 41 tests; +4 from Phase 5 (prune E2E, mint-back persist, recency-order, pipe-safety). All four guard tests present and passing. |
| 3 | SC3: `docs/installation.md` and `references/setup.md` describe the prune-markers.sh operator invocation, default retention (30 days), env override (`REVENIUM_MARKER_RETENTION_DAYS`), and marker file location | VERIFIED | `docs/installation.md` has `## Operational hygiene` section (lines 66-87) with dry-run/live invocations, 30-day default, env override, and cross-reference to `references/setup.md`. `references/setup.md` has `## Marker file pruning` section (lines 112-166) with full operator runbook including manual UAT triple-case. Both files are consistent in env var name, default, flag surface, and ledger-vs-mtime contract. |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `skills/revenium/scripts/common.sh` | `MARKER_RETENTION_DAYS` and `PRUNE_LOCK_FILE` declared after `LOCK_FILE` | VERIFIED | Lines 21-22: `MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"` and `PRUNE_LOCK_FILE="${STATE_DIR}/prune.lock"`. `mkdir -p` block (line 24) is byte-unchanged. `MARKERS_DIR` and `MARKERS_READY_DIR` regex assertions in `test_runtime_paths_are_hermes_native` still pass. |
| `skills/revenium/scripts/prune-markers.sh` | New operator-invoked script; `set -euo pipefail`; sources `common.sh`; `ensure_path`; `--dry-run` flag; `flock` pattern; `info` log helper; summary line | VERIFIED | File exists; `chmod +x` confirmed (`.rwxr-xr-x`); `bash -n` passes; uses `set -euo pipefail` (line 8); sources `common.sh` (line 12) with `# shellcheck source=/dev/null` (line 11); calls `ensure_path` (line 14); parses `--dry-run` flag (lines 20-25); acquires `${PRUNE_LOCK_FILE}` via `exec 9>` + Python `fcntl.flock(LOCK_EX|LOCK_NB)` (lines 32-43); logs via `info` helper (line 51); emits `prune: summary, scanned=... kept=... removed=...` at end (lines 157-163). |
| `skills/revenium/plugins/revenium-classifier/classifier.py` | `_persist_label_to_taxonomy` helper (D-32); `_read_taxonomy_labels` rewritten recent-first (D-33); `_count_tools_in_current_turn` PRESERVED (D-37) | VERIFIED | `_persist_label_to_taxonomy` at line 370: excludes `'unclassified'` sentinel, reads taxonomy, upserts `last_seen_at`, writes via `tmp + os.replace` atomically, fail-open via `try/except`. Called at lines 465 and 499 in `run_classification_async` (parent_task path and LLM-classified path; NOT at line 475 unclassified/halted path). `_read_taxonomy_labels` at line 254: rewritten with `recent_cutoff` (7-day window), splits `recent` vs `older` buckets, sorts recent descending by timestamp, returns `recent + older`. `_count_tools_in_current_turn` at line 79: preserved byte-unchanged. |
| `tests/test_repository.py` | `prune-markers.sh` in expected list; 4 new tests; WR-03 base_env extensions | VERIFIED | Line 74: `SKILL / 'scripts' / 'prune-markers.sh'` in expected list. Four new test methods: `test_prune_markers_dry_run_and_live` (3117), `test_read_taxonomy_labels_recency_order` (3222), `test_persist_label_to_taxonomy_mint_and_update` (3253), `test_hermes_report_pipe_safety_marker_sanitization` (3290). WR-03 env isolation: `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKERS_READY_DIR`, `REVENIUM_TAXONOMY_FILE` added to `base_env` at lines 2833-2835, 2898-2900, 3087-3089. Total test count: 45 (confirmed by `python3 -m unittest discover`). |
| `skills/revenium/scripts/hermes-report.sh` | WR-01 sanitization comment + loop; WR-02 dead `row` variable removed | VERIFIED | Line 529: `# WR-01: sanitize pipe-delimiters and control chars...` comment present. Lines 531-533: `for _bad in ('|', '\n', '\r'): m_agent = m_agent.replace(_bad, '_'); m_trace = m_trace.replace(_bad, '_')` present. Line 552: `local muid t_type op_type d_in d_out d_cr d_cw d_tot d_cost m_agent m_trace` — `row` variable absent. |
| `docs/installation.md` | `## Operational hygiene` section | VERIFIED | Lines 66-87: full section with prune-markers.sh invocations, 30-day default, `REVENIUM_MARKER_RETENTION_DAYS` override, marker location, cross-reference to setup.md. |
| `skills/revenium/references/setup.md` | `## Marker file pruning` section after `## Mechanical classification hook` | VERIFIED | Lines 112-166: full operator runbook with how-to-run commands, manual UAT triple-case fixture, retention override. `## Mechanical classification hook` section at line 88 is byte-unchanged (`test_setup_md_has_mechanical_classification_hook_section` passes). |
| `skills/revenium/references/task-taxonomy.md` | Opening paragraph rewritten to mint-first; `## Mint policy` section rewritten | VERIFIED | Lines 11-15: "classifier reads ${TAXONOMY_FILE} as a recency-ordered reference list. The classifier mints a specific descriptive label by default; existing labels are reused only when they describe the SAME specific work". Lines 73-87: `## Mint policy` body is mint-first framing with citation to 260514-nfb and note that "the classifier plugin persists the new entry to ${TAXONOMY_FILE} automatically". |
| `README.md` | Prune-markers.sh entry in `## Manual commands` | VERIFIED | Lines 166-167: `# Prune stale marker files (30+ days old by default; --dry-run to preview)` and `bash ~/.hermes/skills/revenium/scripts/prune-markers.sh` present between `clear-halt.sh` entry and `install-cron.sh` entry. |
| `.planning/PROJECT.md` | D-3 and D-8 rows rewritten; `## Evolution Notes` section appended | VERIFIED | Line 176 (D-3): "LLM mints specific labels; reuses only on exact match ... Shipped (Phase 5)". Line 181 (D-8): "D-07 heuristic skip removed (was dead code) ... Shipped (Phase 5)". Lines 201-211: `## Evolution Notes` section with 2-row table (D-3 / 260514-nfb; D-8 / 260514-n8e). Footer updated to "2026-05-14 after Phase 5 housekeeping". |
| `.planning/REQUIREMENTS.md` | COMPAT-04 and TEST-05 flipped to `[x]`; traceability table "Verified (Phase 5)" | VERIFIED | Line 66: `- [x] **COMPAT-04**`. Line 74: `- [x] **TEST-05**`. Traceability table lines 171 and 176: both show `Verified (Phase 5)`. Footer updated to reference Phase 5. |
| `.planning/ROADMAP.md` | Phase 5 `[x]` in overview; 4/4 in Progress Table; 4 plan entries with `[x]` | VERIFIED | Line 16: `- [x] **Phase 5: Housekeeping & Compat Hardening**`. Lines 94-97: all four plan entries checked `[x]`. Progress Table line 157: `4/4 | Executed | 2026-05-14`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `prune-markers.sh` | `common.sh` (MARKERS_DIR, LEDGER_FILE, MARKER_RETENTION_DAYS, PRUNE_LOCK_FILE) | `source "${SCRIPT_DIR}/common.sh"` with shellcheck directive | WIRED | Line 11-12: `# shellcheck source=/dev/null` + `source "${SCRIPT_DIR}/common.sh"`. All five variables consumed in the Python heredoc at lines 57-60. |
| `prune-markers.sh` lock | `PRUNE_LOCK_FILE` | `exec 9>"${PRUNE_LOCK_FILE}"` + `fcntl.flock(9, LOCK_EX|LOCK_NB)` | WIRED | Lines 32-43: canonical cron.sh pattern replicated with `PRUNE_LOCK_FILE` (not shared with `LOCK_FILE`). |
| `prune-markers.sh` staleness check | `LEDGER_FILE` | `grep "^HERMES:${sid}:"` via Python heredoc | WIRED | Lines 65-89: `ledger_last_ts` function reads ledger by prefix match, returns float unix ts from field index 3. Orphan fallback to `os.path.getmtime`. |
| `test_prune_markers_dry_run_and_live` | `prune-markers.sh` | `subprocess.run(['bash', str(PRUNE_SCRIPT), ...], env=env)` | WIRED | Line 3189: dry-run invocation; line 3201: live run; line 3213: idempotent re-run. Env carries `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKER_RETENTION_DAYS='30'`, `HERMES_HOME`, `REVENIUM_STATE_DIR`, `TZ='UTC'`. |
| `test_expected_files_exist` | `prune-markers.sh` | `SKILL / 'scripts' / 'prune-markers.sh'` in expected list | WIRED | Line 74: path present. `test_shell_scripts_have_valid_syntax` auto-picks it via `SKILL.rglob('scripts/*.sh')` — no separate edit needed. |
| `run_classification_async` (parent_task path, line 465) | `_persist_label_to_taxonomy` | Direct call after `await asyncio.to_thread(_write_marker_pair, ...)` | WIRED | Line 465: `_persist_label_to_taxonomy(parent_task)` inside the parent-task inheritance branch. |
| `run_classification_async` (LLM path, line 499) | `_persist_label_to_taxonomy` | Direct call after `await asyncio.to_thread(_write_marker_pair, ...)` | WIRED | Line 499: `_persist_label_to_taxonomy(task_type)` inside the LLM-classified branch. NOT called at the unclassified/halted path (line 475) — sentinel correctly excluded. |
| `_persist_label_to_taxonomy` | `TAXONOMY_FILE` | `tmp + os.replace` atomic write | WIRED | Lines 403-405: `tmp = TAXONOMY_FILE.parent / (TAXONOMY_FILE.name + ".tmp"); tmp.write_text(...); tmp.replace(TAXONOMY_FILE)`. Same-filesystem guarantee honored (temp in same parent dir). |
| `_read_taxonomy_labels` | `_build_classification_prompt` | Return value consumed by caller | WIRED | Line 328: `labels = _read_taxonomy_labels()` called inside `_classify_via_llm`. 1024-byte cap at line 298 is byte-unchanged. |
| `test_wire_agent_trace_passthrough` base_env (lines 2833-2835) | `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKERS_READY_DIR`, `REVENIUM_TAXONOMY_FILE` | Explicit overrides added to base_env | WIRED | Three new env keys at lines 2833-2835 and 2898-2900 (two base_env constructions for two sub-cases). |
| `test_wire_no_provider_regression_per_class` base_env (line 3087-3089) | `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKERS_READY_DIR`, `REVENIUM_TAXONOMY_FILE` | Explicit overrides added to base_env | WIRED | Lines 3087-3089 inside the 8-case DRY loop. |

### Data-Flow Trace (Level 4)

Not applicable to this phase. Phase 5 ships operator scripts and doc updates — no dynamic data-rendering components.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `prune-markers.sh` passes `bash -n` syntax check | `bash -n skills/revenium/scripts/prune-markers.sh` | exit 0, "SYNTAX OK" | PASS |
| `prune-markers.sh` is executable | `ls -la prune-markers.sh` | `.rwxr-xr-x` | PASS |
| Full test suite (45 tests) | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | `Ran 45 tests in 14.731s — OK` | PASS |
| `_persist_label_to_taxonomy` exists in classifier.py | `grep -n "_persist_label_to_taxonomy" classifier.py` | Found at lines 370, 465, 499 | PASS |
| `_count_tools_in_current_turn` preserved (D-37) | `grep -n "_count_tools_in_current_turn" classifier.py` | Found at line 79 (definition) + references | PASS |
| `_read_taxonomy_labels` rewritten with recency ordering | Code inspection | `recent_cutoff`, `recent`, `older` buckets, `recent.sort(..., reverse=True)` present | PASS |
| `local row` removed from hermes-report.sh WR-02 | `grep -n "local row" hermes-report.sh` | Returns `local muid t_type ...` (no `row`) | PASS |
| WR-01 sanitization loop present | `grep -n "for _bad in" hermes-report.sh` | Found at line 531 | PASS |
| COMPAT-04 checkbox flipped in REQUIREMENTS.md | `grep "COMPAT-04" REQUIREMENTS.md` | `- [x] **COMPAT-04**` | PASS |
| TEST-05 checkbox flipped in REQUIREMENTS.md | `grep "TEST-05" REQUIREMENTS.md` | `- [x] **TEST-05**` | PASS |
| Traceability table entries updated | `grep "Verified (Phase 5)" REQUIREMENTS.md` | Lines 171, 176 both show "Verified (Phase 5)" | PASS |
| Phase 5 `[x]` in ROADMAP overview | `grep "Phase 5.*Housekeeping" ROADMAP.md` | `[x] **Phase 5: Housekeeping ...` | PASS |
| 4/4 Progress Table in ROADMAP | `grep "4/4.*Executed" ROADMAP.md` | Line 157: `4/4 | Executed | 2026-05-14` | PASS |
| `## Evolution Notes` in PROJECT.md | `grep "Evolution Notes" PROJECT.md` | Section exists at line 201 with 2-row table | PASS |

### Probe Execution

No probe scripts declared. Step 7c SKIPPED (no `scripts/*/tests/probe-*.sh` in this phase).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| COMPAT-04 | 05-01, 05-02, 05-03, 05-04 | Frontmatter contract (`name: revenium`, `metadata.hermes`, `category: devops`) preserved; `test_skill_frontmatter_has_hermes_metadata` passes | SATISFIED | `test_skill_frontmatter_has_hermes_metadata` passes in 45-test suite. `[x]` checkbox in REQUIREMENTS.md. Traceability: "Verified (Phase 5)". |
| TEST-05 | 05-01, 05-02, 05-03, 05-04 | `test_no_legacy_branding_left` continues to pass for new content | SATISFIED | `test_no_legacy_branding_left` passes in 45-test suite. `[x]` checkbox in REQUIREMENTS.md. Traceability: "Verified (Phase 5)". No TBD/FIXME/XXX debt markers found in Phase 5 modified files. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `skills/revenium/plugins/revenium-classifier/classifier.py` | 370-407 | `_persist_label_to_taxonomy` uses fixed `.tmp` filename without `fcntl.flock` | WARNING | Deviates from atomic-write pattern documented in `references/task-taxonomy.md`. Two concurrent `on_session_end` events could race on the same `.tmp` file. Practical risk is low (session-end events are rarely concurrent). REVIEW.md WR-01 documents this and provides a fix using `tempfile.NamedTemporaryFile` + `flock`. Deferred by operator pending v1.1. |
| `skills/revenium/scripts/prune-markers.sh` | 57-60 | `${VAR@Q}` interpolation into Python heredoc | WARNING | Paths containing single quotes produce a Python `SyntaxError`. Script crashes cleanly under `set -e` rather than silently misbehaving. Operator-controlled paths rarely contain single quotes. REVIEW.md WR-02 documents fix via env-var pattern. Deferred by operator. |
| `skills/revenium/scripts/prune-markers.sh` | 59 | `int(${MARKER_RETENTION_DAYS@Q})` accepts negative/zero values | WARNING | `REVENIUM_MARKER_RETENTION_DAYS=0` makes every marker appear stale (cutoff_secs=0). A typo could wipe the entire marker corpus. REVIEW.md WR-02 includes validation fix. Deferred by operator. |
| `skills/revenium/scripts/prune-markers.sh` | 32-43 | Lock acquisition does not include `LOCK_FILE` (cron.lock) | WARNING | Concurrent `prune-markers.sh` + cron tick can race on marker file deletion. On POSIX `unlink` during an open read is safe, but a plugin `_write_marker_pair` write immediately after prune unlinks would write to a stale inode. Low practical risk (operator-invoked, infrequent). REVIEW.md WR-03 documents fix. Deferred by operator. |
| `tests/test_repository.py` | 3275-3279 | `first_ts` captured but `last_seen_at` update never asserted | WARNING | `test_persist_label_to_taxonomy_mint_and_update` sub-case 2 only asserts `len(data2['labels']) == 1`, not that `last_seen_at` was updated. The update behavior (D-33) is unverified by this test. REVIEW.md WR-04 documents fix with `time.sleep(1)` guard. Advisory. |

Note: No TBD/FIXME/XXX debt markers found in any Phase 5 modified files. All advisory warnings above are from REVIEW.md (advisory, non-blocking) and have been explicitly deferred by the operator pending v1.1.

### Human Verification Required

#### 1. Live operator run of prune-markers.sh

**Test:** On a Hermes host that has been running for more than 30 days, export `REVENIUM_MARKER_RETENTION_DAYS=30` and run `bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run`. Confirm expected candidates are listed. Then run without `--dry-run`. Check `tail ~/.hermes/state/revenium/revenium-metering.log` for per-deletion info lines and the summary line.
**Expected:** Old marker files removed; fresh-session markers kept; log shows `prune: removed sid=... marker=... last_ledger_ts=... age_days=...` per deletion and `prune: summary, scanned=N kept=K removed=R` at the end.
**Why human:** The E2E test covers a synthetic 3-marker fixture. Real-world validation against genuine `~/.hermes/state/revenium/` data is the full acceptance bar for SC1. A real host also exercises the actual cron.lock / prune.lock interaction under realistic timing.

#### 2. Edge case: `REVENIUM_MARKER_RETENTION_DAYS=0` behavior

**Test:** Run `REVENIUM_MARKER_RETENTION_DAYS=0 bash ~/.hermes/skills/revenium/scripts/prune-markers.sh --dry-run` on a host with marker files.
**Expected:** Either: (a) script exits with a clear validation error ("REVENIUM_MARKER_RETENTION_DAYS must be >= 1"), or (b) every marker is listed as a dry-run candidate (integer 0 makes every file appear stale). The operator should know which behavior to expect so they don't accidentally wipe their marker corpus.
**Why human:** REVIEW.md WR-02 flags this as an unvalidated edge case. Automated tests always pass `30`. An operator typo or misconfiguration could trigger unintended bulk deletion. The operator needs to confirm the behavior before shipping to a wider audience or decide to add the validation gate.

### Gaps Summary

No gaps blocking goal achievement. All three ROADMAP success criteria are met by code and tests present in the repository:

- SC1 (prune script idempotent against fixture): Verified by `test_prune_markers_dry_run_and_live` passing against the full 3-case fixture.
- SC2 (full suite green at 45 tests): Verified by `python3 -m unittest discover` showing `Ran 45 tests — OK`.
- SC3 (docs describe contract + prune invocation): Verified by presence and content of `## Operational hygiene` in `docs/installation.md` and `## Marker file pruning` in `references/setup.md`.

Two human verification items exist (live operator run + zero-retention edge case) — neither blocks the automated goal but both represent acceptance criteria that require a live Hermes installation to confirm. The code is correct for canonical paths; the human items are defensive edge-case confirmations and production-environment validation.

The four advisory warnings from REVIEW.md (`_persist_label_to_taxonomy` flock deviation, `@Q` path quoting, zero-retention, cron.lock not acquired) are all acknowledged. None are blockers for Phase 5's stated goal. Per the operator decision captured in REVIEW.md, these are deferred to v1.1.

---

_Verified: 2026-05-14_
_Verifier: Claude (gsd-verifier)_
