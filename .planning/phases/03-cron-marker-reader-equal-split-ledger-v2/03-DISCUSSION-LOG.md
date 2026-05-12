# Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 - Discussion Log

**Discussed:** 2026-05-12
**Mode:** discuss (default, no flags)

This is a human-reference log of the discussion that produced `03-CONTEXT.md`. Downstream agents (researcher, planner, executor) consume `03-CONTEXT.md`, not this file.

---

## Pre-Discussion Context Loaded

- `.planning/PROJECT.md` — 9 project decisions (per-turn granularity, agent self-classification, controlled-vocabulary taxonomy, marker file IPC, S2 equal split, --operation-type GUARDRAIL, --task-type unclassified default, classify substantive turns only, agent-managed taxonomy growth)
- `.planning/REQUIREMENTS.md` — Phase 3 has 15 requirement IDs after Phase 2 reassignments (TAX-05, MARK-04, CRON-01..09, COMPAT-02, COMPAT-03, TEST-03, TEST-04)
- `.planning/ROADMAP.md` Phase 3 section — 5 success criteria
- `.planning/STATE.md` — Phase 2 carry-forwards (HERMES_SESSION_ID resolution, TAX-05 + MARK-04 reassignments, S2 bias framing discrepancy flagged)
- `.planning/research/PITFALLS.md` — Pitfall 5 (S2 bias one-directional), Pitfall 8 (per-marker ledger MUST ship atomically with deterministic transaction-id + per-call writes)
- Phase 1 CONTEXT.md (read sub-recently for path discipline carry-forward)
- Phase 2 CONTEXT.md (marker schema, taxonomy shape, HERMES_SESSION_ID decision tree)

## Codebase Scout

- `skills/revenium/scripts/hermes-report.sh` — 268 lines; existing per-session loop is the surface Phase 3 extends. Python heredoc patterns at lines 90, 115-165, 179, 216-251. Array-built CLI argv at 216-249.
- `skills/revenium/scripts/budget-check.sh` — 117 lines; Python heredoc analog for atomic writes (tempfile.NamedTemporaryFile + os.rename pattern).
- `skills/revenium/scripts/common.sh` — 40 lines; single source of truth for state paths. Phase 3 will add LOCK_FILE.
- `.planning/codebase/ARCHITECTURE.md` — Existing two-half design (cron pipeline + skill prompt) communicating via filesystem state.
- `.planning/codebase/CONCERNS.md` — Tracks the unversioned ledger as known tech debt (Phase 3 addresses this).

## Gray Areas Identified

Four phase-specific gray areas surfaced after analysis:

1. **Phase shape & wave structure** — 15 requirements + "one coherent migration" constraint
2. **Pluggable split seam (CRON-09)** — function-only vs Python class? Heredoc vs standalone module?
3. **Ledger v1→v2 versioning & migration** — discrimination strategy for legacy rows
4. **Concurrency, tolerance, and S2 bias framing** — flock semantics, TAX-05/MARK-04 placement, PITFALLS vs PROJECT.md bias framing

User selected all four for discussion.

---

## Area 1: Phase shape & wave structure

**Question presented:** Phase 3 has 15 requirements; PITFALLS Pitfall 8 says per-marker ledger + deterministic transaction-id + per-call writes MUST ship together. Most plans will touch hermes-report.sh so waves serialize anyway. How should the planner decompose the 15 requirements?

**Options:**
1. Single fat plan (Recommended) — one 03-01-PLAN.md, atomic ship
2. Two-plan split: core migration + compat/telemetry
3. Three-plan split by surface

**User decision:** Single fat plan.

**Rationale:** Atomic ship enforces PITFALLS Pitfall 8 by construction. Alternative splits serialize anyway because of shared `hermes-report.sh` file ownership; smaller plans add the risk of mid-migration state if execution interrupts between plans. Plan executor will need to commit in a logical sequence (D-02) so each intermediate commit keeps tests green.

---

## Area 2: Pluggable split seam (CRON-09)

**Question presented:** CRON-09 requires 'a pluggable seam (single function or Python class) so S3/S4 can drop in later without touching the cron's outer loop'. The cron is bash with Python heredocs. Where should the split strategy live?

**Options:**
1. Standalone Python module at `scripts/split_strategies.py` (Recommended)
2. Python heredoc with named function inside `hermes-report.sh`
3. Standalone Python module + bash dispatcher pattern with SPLIT_STRATEGY env var

**User decision:** Standalone Python module at `scripts/split_strategies.py`.

**Rationale:** Testable in isolation via unittest, clean S3/S4 extension path. The cost (one new file, must be added to `test_expected_files_exist`) is acceptable for the test-isolation gain. Heredoc-only would bloat as S3/S4 are added; full dispatcher pattern is over-engineered for v1 when S3/S4 are explicitly deferred to v2.

---

## Area 3: Ledger v1→v2 versioning & migration

**Question presented:** CRON-05 says v2 format is HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids> (5 colon-separated fields). v1 had 4 fields. PITFALLS Pitfall 8 also recommends a version sentinel. The reader must discriminate v1 vs v2 to skip v1 lines correctly. Which discrimination strategy?

**Options:**
1. Field-count discrimination (Recommended) — len(parts) switch
2. Explicit version prefix HERMES:v2:...
3. Sentinel-based discrimination on the 5th field (`:M:` suffix)

**User decision:** Field-count discrimination.

**Rationale:** Simpler; existing v1 rows parse cleanly under CRON-05's "no markers reported yet for this delta" wording without any in-place rewrite. Acceptable that future v3 would need 6 fields or a new sentinel — v3 is not planned. PITFALLS Pitfall 8's version-sentinel recommendation is one of several valid approaches; the team's choice is field-count.

---

## Area 4: Concurrency, tolerance, and S2 bias framing

### Sub-question 4a: flock(2) semantics on cron.lock

**Options:**
1. Non-blocking + exit 0 with warn log (Recommended)
2. Non-blocking + exit non-zero
3. Block + wait with timeout

**User decision:** Non-blocking + exit 0 with warn log.

**Rationale:** Matches ROADMAP SC4 verbatim ("exit cleanly with a prior tick still active log line"). Cron retries next minute; no missed work in normal operation. Exit 0 avoids spurious cron mail.

### Sub-question 4b: TAX-05 + MARK-04 tolerance placement

**Options:**
1. Per-session loop with per-failure try/except (Recommended)
2. Preflight at top of main() with global fail-open flag
3. Hybrid: preflight taxonomy, per-session marker tolerance

**User decision:** Per-session loop with per-failure try/except.

**Rationale:** Per-session isolation — one bad session shouldn't drop the whole cron run to unclassified. Slight extra code is justified by correctness; matches the spirit of TAX-05's "taxonomy corruption does not break metering" wording.

### Sub-question 4c: S2 bias framing in references/setup.md

**Options:**
1. PITFALLS framing: one-directional, GUARDRAIL is an upper bound (Recommended)
2. Self-cancels framing (PROJECT.md original)

**User decision:** PITFALLS framing (one-directional).

**Rationale:** Empirically correct per PITFALLS Pitfall 5 analysis; "self-cancels" framing in PROJECT.md is wrong and STATE.md flagged this discrepancy for resolution. Ships honest operator-facing documentation. PROJECT.md itself will be updated in a Phase 5 housekeeping pass (deferred per D-16 to avoid project-doc churn mid-Phase-3).

---

## Final Confirmation

**Question:** All 4 areas discussed: single fat plan, standalone split_strategies.py module, field-count discrimination for v1→v2 ledger, non-blocking lock + per-session tolerance + one-directional bias framing. Any remaining unclear areas before I write CONTEXT.md?

**User decision:** Ready for CONTEXT.md.

---

## Claude's Discretion Items

The following implementation-level details were left to the planner/executor:

- Exact wording of `warn`/`info` log lines beyond the locked phrases
- Byte-exact algorithm for equal-split remainder absorption (last marker vs round-robin), subject to conservation invariant
- Field-name conventions inside `split_strategies.equal_split`'s input/output dicts
- Exact location of the `## How attribution works` section in `references/setup.md`
- Whether to create `test_split_strategies_module` or roll splitter tests into existing `tests/test_repository.py`

## Deferred Ideas

- S3 (weighted) and S4 (guardrail-estimator) split strategies — already deferred per PROJECT.md decision 5
- PROJECT.md "bias self-cancels" cleanup — defer to Phase 5 housekeeping pass
- Ledger migration script — explicitly NOT shipping; v1 rows stay forever
- Per-tick metering log line verbosity flag — ship the noisier version in v1
- Telemetry export of bias warnings to Revenium — out of scope for v1

---

*Discussion completed: 2026-05-12*
