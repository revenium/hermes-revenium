# Phase 5: Housekeeping & Compat Hardening — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Operational hygiene for the now-shipping Hermes-Revenium task-type metering pipeline. Three concerns:

1. **Marker file pruning** — long-running Hermes hosts accumulate marker JSONL files indefinitely; ship `prune-markers.sh` and an operator runbook.
2. **Compat invariants stay pinned** — frontmatter (`name: revenium`, `metadata.hermes`, `category: devops`), legacy-branding guard, runtime-path discipline, and shell-syntax checks continue to pass at the end of Phase 5 (COMPAT-04, TEST-05).
3. **Truth refresh** — bring docs and PROJECT.md decisions back in sync with shipping behavior after today's three classifier-chain quick tasks (260514-n8e, 260514-nfb, 260514-nz8). Three load-bearing project decisions (D-3 lookup-first taxonomy reuse, D-8 D-07 trivial-skip) no longer match the code; setup.md and references/task-taxonomy.md have stale framings.

Plus cleanup folded in from Phase 4 code review (WR-01, WR-02, WR-03).

**Out of scope (explicit):**
- `_count_tools_in_current_turn` helper removal (kept as-is per D-37 below)
- Further refactor of `classifier.py` for clarity post-D-07 (no forcing function)
- Any new requirements beyond COMPAT-04 / TEST-05
- Any change to the live wire contract (`hermes-report.sh` argv shape, marker schema, ledger format)
- Any new state files outside `${STATE_DIR}`

</domain>

<decisions>
## Implementation Decisions

### Prune-markers (`prune-markers.sh` — the new artifact)
- **D-26: Stale criteria = "latest ledger row for sid older than N days".** The prune script reads `revenium-hermes.ledger`, finds the most recent `HERMES:<sid>:…:<unix_ts>:…` entry per sid, and removes the marker file only if that timestamp is older than the retention threshold. Authoritative against the existing idempotency contract; never deletes markers whose tokens haven't been fully reported yet. Falls back to mtime-only when no ledger entry exists for a sid (orphan marker — safe to remove on the same retention threshold).
- **D-27: Default retention = 30 days, configurable via `$REVENIUM_MARKER_RETENTION_DAYS`.** Declared in `common.sh` adjacent to `MARKERS_DIR` (preserves the single-source-of-truth path discipline). Soft default in `common.sh`: `MARKER_RETENTION_DAYS="${REVENIUM_MARKER_RETENTION_DAYS:-30}"`.
- **D-28: Operator-invoked only — no auto-run from `cron.sh`.** Documented in `references/setup.md` as a periodic operator action. Matches the project's existing operator-runbook pattern (`clear-halt.sh`, `install-cron.sh`). No new install surface, no new crontab line. Future iteration may add an `install-prune-cron.sh` opt-in.
- **D-29: Safety = `--dry-run` flag + `info`-helper log every deletion.** `prune-markers.sh --dry-run` lists files that would be removed without touching them. Real runs log every deletion via `info` to `${LOG_FILE}` so the operator can audit. Lock-file pattern (same flock-based serial gate as `hermes-report.sh`) prevents concurrent prune runs from racing on the same file set.

### PROJECT.md truth refresh
- **D-30: Rewrite D-3 and D-8 in place + add `## Evolution Notes` subsection.** D-3 ("Controlled-vocabulary taxonomy with strict lookup-first reuse") and D-8 ("Classify substantive turns only — D-07 heuristic skip") get rewritten to match shipping behavior (mint-first prompt, no trivial-skip — D-7 fallback path remains). A new `## Evolution Notes` section at the bottom of PROJECT.md captures the dated transition: "D-3 rewritten 2026-05-14 — lookup-first reuse pressure removed via quick task 260514-nfb; LLM mints specific labels and only reuses on identical work. D-8 obsoleted — D-07 heuristic skip was dead code (response always None at the entrypoint); quick task 260514-n8e removed it." Decisions stay current; history preserved separately.
- **D-31: Audit + fix all references to taxonomy/D-07 across docs.** Phase 5 grep sweep over `references/task-taxonomy.md`, `references/setup.md`, and README.md for any claim that contradicts current classifier behavior (lookup-first reuse pressure, trivial-skip semantics, agent-managed-only taxonomy growth). Fix what's stale; preserve unchanged content. One file per atomic commit.

### Taxonomy file persistence (mint-back)
- **D-32: Persist newly-minted labels back to `task-taxonomy.json` on every successful classification.** After `_validate_label` returns a label and `_write_marker_pair` succeeds, append the label to `task-taxonomy.json` if not already present. Schema extension: each label entry gets a `last_seen_at` field (ISO timestamp) so the prompt can recency-order. Description and examples remain optional (null for newly-minted labels). Write atomically via temp-file + rename (mirrors the marker pattern). Fail-open: any I/O error logs a warning and continues (does not affect marker write).
- **D-33: Prompt orders existing labels recent-first, alphabetical within recency bucket.** `_read_taxonomy_labels()` returns labels sorted by `last_seen_at` descending (recent-first), alphabetical within ties. Labels minted in the last 7 days appear in a "recent" bucket; older labels follow. Helps the LLM see the project's CURRENT vocabulary first when deciding whether to reuse. Labels without `last_seen_at` (seed labels) get treated as "older" and sort alphabetically at the end. The 1024-byte cap on `labels_block` is preserved.

### Cleanup (Phase 4 review WRs)
- **D-34: WR-01 — pipe-safety sanitization for marker `agent`/`trace_id` fields.** In `hermes-report.sh::split_rows` Python heredoc, sanitize `m_agent` and `m_trace` before the pipe-delimited print: replace `|`, `\n`, `\r` with `_`. Prevents future upstream writers (currently unused per D-23) from silently corrupting the bash while-read parsing if they ever populate the fields with control characters.
- **D-35: WR-02 — remove dead `local row` variable in `hermes-report.sh`.** Single-line cleanup at the while-read declaration (currently line ~549). Variable declared but never read; relic from a pre-11-pipe iteration.
- **D-36: WR-03 — explicit env isolation in Phase 4 tests.** `test_wire_agent_trace_passthrough` and `test_wire_no_provider_regression_per_class` inherit `os.environ` and only override `HERMES_HOME` / `REVENIUM_STATE_DIR`. Phase 5 extends `base_env` in both tests to also override `REVENIUM_MARKERS_DIR`, `REVENIUM_MARKERS_READY_DIR`, and `REVENIUM_TAXONOMY_FILE`, so a developer with custom env vars cannot leak settings into the test harness.
- **D-37: KEEP `_count_tools_in_current_turn` helper + its 4 tests.** Even though the helper is no longer called after D-07 removal (260514-n8e), it remains useful as an introspection helper for future diagnostics and the 4 tests document its contract. Not removed in Phase 5 (deliberate scope choice). May be revisited in v1.1 if a future review confirms zero callers and no documentation utility.
- **D-38: Scope locked — no other cleanup.** No refactor of `classifier.py` post-D-07; no additional test renames; no other code drift fixes beyond WR-01..03. If something else surfaces during execution, capture as deferred.

### Claude's Discretion
- Exact prune-script flag layout (`--dry-run`, `--retention N`, `--verbose`, etc.) — planner picks the shape that mirrors existing scripts.
- Whether the lock-file path is shared with `cron.sh` or scoped to prune-only — planner picks based on flock contention analysis.
- Migration order for the doc audit (which file first) — planner picks based on file dependencies (PROJECT.md before reference docs typically).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level context (set in stone)
- `CLAUDE.md` — bash conventions (`set -euo pipefail` vs `set -uo pipefail`, common.sh path discipline, Python heredoc stdlib-only rule, no legacy branding), the two halves never call each other invariant, idempotency-via-ledger contract.
- `.planning/PROJECT.md` — core value statement, Key Decisions D-1..D-9 (with D-3 and D-8 explicitly slated for rewrite in this phase per D-30).
- `.planning/REQUIREMENTS.md` — COMPAT-04 and TEST-05 entries (the two requirements this phase ships against). Traceability table — Phase 5 updates these rows to "Verified (Phase 5)" on completion.
- `.planning/ROADMAP.md` Phase 5 row — success criteria (prune script, suite green, docs describing marker/taxonomy contract + S2 bias direction + prune invocation).

### Path / state discipline (load-bearing)
- `skills/revenium/scripts/common.sh` — single source of truth for state paths. The new `MARKER_RETENTION_DAYS` env+default declaration goes here adjacent to `MARKERS_DIR`. `prune-markers.sh` sources this file like every other script.
- `tests/test_repository.py::test_runtime_paths_are_hermes_native` — enforces `.hermes` and `state/revenium` literals remain in common.sh. Any new path lines must keep these intact.
- `tests/test_repository.py::test_skill_frontmatter_has_hermes_metadata` — COMPAT-04 enforcement.
- `tests/test_repository.py::test_no_legacy_branding_left` — TEST-05 enforcement; regex at `tests/test_repository.py:47`.

### Prior phase summaries (reference for what shipped)
- `.planning/phases/04-wire-enrichment/04-01-SUMMARY.md` — wire enrichment + 8-provider regression context; the artifact list that defines what NOT to break.
- `.planning/phases/04-wire-enrichment/04-REVIEW.md` — source of WR-01..03 (the cleanup items folded into Phase 5 via D-34..D-36).
- `.planning/phases/04-wire-enrichment/04-VERIFICATION.md` — proves Phase 4 passed all goal-backward checks.
- `.planning/phases/04-wire-enrichment/04-UAT.md` — operator-facing confirmation (5/5 passed) that the wire works end-to-end.
- `.planning/phases/06-mechanical-classification-agent-end-hook/06-04-SUMMARY.md` — most recent canonical SUMMARY shape this phase mirrors.

### Today's classifier-chain quick tasks (the forcing function for D-30 + D-32)
- `.planning/quick/260514-n8e-remove-d-07-trivial-skip-from-classifier/260514-n8e-SUMMARY.md` — D-07 removal; obsoletes D-8.
- `.planning/quick/260514-nfb-rewrite-classifier-prompt-to-mint-first-/260514-nfb-SUMMARY.md` — mint-first prompt; obsoletes D-3.
- `.planning/quick/260514-nz8-add-state-db-message-lookup-to-classifie/260514-nz8-SUMMARY.md` — content lookup; the architectural reason mint-first actually works on live data.

### Code surfaces touched
- `skills/revenium/scripts/hermes-report.sh` — split_rows Python heredoc (WR-01 sanitization site at lines ~525-535); while-read declaration (WR-02 dead-var site at ~549).
- `skills/revenium/plugins/revenium-classifier/classifier.py` — `_read_taxonomy_labels` (line ~205, recency-order update for D-33); near `_write_marker_pair` (line ~296, mint-back call for D-32).
- `skills/revenium/task-taxonomy.json` — schema extension for `last_seen_at` per label (D-32/D-33).
- `tests/test_repository.py` — `base_env` in the two Phase 4 tests for WR-03 (D-36); new tests for prune script + mint-back + recency ordering.
- `skills/revenium/references/setup.md` — doc updates for prune operator runbook + truth refresh on classifier behavior.
- `skills/revenium/references/task-taxonomy.md` — truth refresh on lookup-first/mint-first framing.
- `README.md` — installation-flow note for marker pruning + any TAX-* claims still framed as lookup-first.
- `.planning/PROJECT.md` — D-3 + D-8 rewrites + new `## Evolution Notes` section.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`info` / `warn` / `error` log helpers** in `common.sh` — timestamped writes to `${LOG_FILE}`. `prune-markers.sh` uses these for every deletion entry (per D-29). Consistent with the rest of the pipeline.
- **`ensure_path`** in `common.sh` — prepends brew/python3 paths. Must be called immediately after sourcing common.sh in the new prune script (same defensive pattern as every other script).
- **Atomic write pattern (temp + rename)** used by `clear-halt.sh:budget-status.json` and the marker writer in `classifier.py::_write_marker_pair`. Mint-back to `task-taxonomy.json` (D-32) uses the same pattern.
- **`flock` lock-file pattern** in `hermes-report.sh::main` and `cron.sh` — `prune-markers.sh` uses the same `flock(fd, LOCK_EX)` shape to serialize against itself and against the cron pipeline.
- **`build_state_db`, `run_cron`, `argv_to_flags`, revenium-shim, `base_env`** helpers in `tests/test_repository.py` (lines 373-491) — reused by new tests for the prune script (state.db + ledger setup, no revenium calls needed) and for mint-back tests.

### Established Patterns
- **All state paths in `common.sh`, nothing inline** — D-26/D-27 add `MARKER_RETENTION_DAYS` adjacent to `MARKERS_DIR`. `test_runtime_paths_are_hermes_native` continues to pass.
- **Operator scripts call `info`, never bare `echo` for logged events** — D-29's "log every deletion" follows.
- **Tests live in `tests/test_repository.py`, no other files** — no new test files; methods append to `RepositoryTests`.
- **Idempotency via ledger** — the ledger row `HERMES:<sid>:<total_tokens>:<unix_ts>:<muid>` is the authoritative record of "this token was reported"; D-26's stale-criteria reads the timestamp field (`<unix_ts>`, the 4th colon-segment).

### Integration Points
- **Prune script → `revenium-hermes.ledger`:** read-only `grep "^HERMES:<sid>:" | tail -1 | cut -d: -f4` per marker file. Never writes the ledger.
- **Prune script → marker dir:** removes JSONL files when ledger timestamp is older than retention. Never touches `markers-ready/` (sentinel dir) — those are managed by the classifier plugin's D-21 sentinel write.
- **Classifier mint-back → `task-taxonomy.json`:** writes via `json.dump` to a temp file then `os.replace`. Failure mode (D-32): log-warn-continue, do not affect marker write.
- **PROJECT.md → researcher / planner / executor agents:** D-3 and D-8 are read by these agents at every phase. Rewriting them ensures Phase 6+ work doesn't accidentally re-introduce the old framing.

</code_context>

<specifics>
## Specific Ideas

- **Schema for mint-back label entry** (D-32): existing seed entries look like `"generation": {"description": "...", "examples": ["..."]}`. New minted entries get `"moltbook_heartbeat_check": {"description": null, "examples": [], "last_seen_at": "2026-05-14T21:28:02Z"}`. `last_seen_at` is the only new field; existing entries get the field on first read (lazy migration via `dict.get("last_seen_at", ...)`).
- **Prune-script logging format** (D-29): `info "prune: removed sid=<sid> marker=<basename> last_ledger_ts=<iso> age_days=<n>"` per deletion. `info "prune: dry-run, would remove sid=<sid> ..."` for dry-run. `info "prune: summary, scanned=<n> kept=<n> removed=<n>"` at end of run.
- **Operator UAT for prune** (success criterion 1 verification): seed `${MARKERS_DIR}` with one marker whose latest ledger row is 31 days old, one whose latest is today, plus one orphan (no ledger row, mtime 31 days ago). Run `bash prune-markers.sh --dry-run`, confirm the 31-day-old + orphan are in the dry-run list and today's is not. Run without `--dry-run`, confirm same. Run again immediately — exit 0 with `removed=0` (idempotent). This is the manual operator runbook the SUMMARY.md should embed.
- **PROJECT.md Evolution Notes format** (D-30): one entry per change, dated, with quick-task ID and one-sentence rationale. Future entries append below.

</specifics>

<deferred>
## Deferred Ideas

- **Auto-invoke prune from cron.sh** (D-28 alternative) — operator-only for now; revisit in v1.1 if operators report forgetting to run it.
- **Trash directory instead of delete** (D-29 alternative) — current plan goes straight to `rm` + log; trash recovery is overkill given Revenium dashboard retention covers the analytics need.
- **`_count_tools_in_current_turn` helper removal** (D-37 explicit defer) — kept for introspection; v1.1 reconsiders if zero callers remain after Phase 5.
- **Mint-back staging (require N appearances before persisting)** (D-32 alternative) — current plan persists on first appearance; if taxonomy noise becomes a problem, add a staging layer in v1.1.
- **`install-prune-cron.sh` opt-in installer** — natural future addition once D-28 patterns prove the operator-only path is too manual.
- **Classifier.py refactor for clarity post-D-07** (D-38 explicit defer) — no forcing function in v1; revisit when next changing the classifier.

</deferred>

---

*Phase: 5-Housekeeping-Compat-Hardening*
*Context gathered: 2026-05-14*
