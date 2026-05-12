# Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 ships the cron half of the agent ↔ cron marker contract. Concretely, `skills/revenium/scripts/hermes-report.sh` is extended to:

1. **Read markers** from `${MARKERS_DIR}/<sid>.jsonl` for each session in `state.db` since the previous ledger row's `ts`, skipping any `muid` already present in the prior row's tail.
2. **Equal-split delta** — for a session with N markers in the window, split `input/output/cache_read/cache_write/cost/total` equally across the N markers, remainder absorbed by the last marker so summed splits equal the input delta byte-for-byte (conservation invariant — TEST-03 / COMPAT-02).
3. **Emit one `revenium meter completion` per marker** with that marker's `--task-type` and `--operation-type` plus the per-split numeric fields.
4. **Extend `--transaction-id`** to `${sid}-${total_tokens}-${muid}` so Revenium server-side dedupe catches retries even if the local ledger is lost (CRON-04).
5. **Extend ledger row v2** to `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>` (5 colon-separated fields). v1 4-field rows remain readable and parse as "no markers reported yet for this delta" (CRON-05).
6. **Per-call ledger writes** — each successful `revenium meter completion` appends one v2 row before the next call starts (CRON-06). A partial multi-call failure leaves a recoverable state on the next tick.
7. **Pluggable split strategy** — `equal_split` lives in a new standalone Python module at `skills/revenium/scripts/split_strategies.py` so S3 (weighted) and S4 (guardrail-estimator) can drop in later without touching `hermes-report.sh`'s outer loop (CRON-09).
8. **`flock(2)` cron lock** on `~/.hermes/state/revenium/cron.lock` prevents overlapping cron ticks from racing on the ledger; second tick exits cleanly with a `prior tick still active` warn-log and exit 0 (CRON-08).
9. **Zero-marker fallthrough** — when N == 0 markers in the window (older install, agent didn't classify, missing file), the cron falls through to the existing single-call path with the addition of `--task-type unclassified` and no explicit `--operation-type` (CRON-07).
10. **Per-session fail-open tolerance** — `TAX-05` (missing/malformed taxonomy file) and `MARK-04` (torn last JSON line in marker file) both catch parse failures in the per-session loop and fall through to `--task-type unclassified` with a `warn` log. One bad session does NOT drop the whole cron run.
11. **Synthetic-bias telemetry** — when a window matches the S2-bias predicate (small classification turn + large work turn), emit a `S2: classification-dominated window` warn-log line (TEST-04, Pitfall 5).
12. **References doc update** — `skills/revenium/references/setup.md` gains a "How attribution works" section that documents the one-directional S2 bias framing (GUARDRAIL share is an upper bound, NOT an estimate; bias does NOT self-cancel — supersedes the PROJECT.md "self-cancels" framing).

Out of scope this phase:
- Wire enrichment (`--operation-type` / `--agent` / `--trace-id` from marker fields) — Phase 4 owns this. CRON-03 ships only the per-marker `--task-type` and `--operation-type` from the marker's own fields; provider/agent/trace defaults remain today's hardcoded values.
- Marker file pruning, end-to-end test fixtures, frontmatter / branding / runtime-path housekeeping — Phase 5.
- S3 (weighted) or S4 (guardrail-estimator) strategies — deferred to v2 per PROJECT.md decision 5.

Critical ordering constraint (PITFALLS Pitfall 8): per-marker ledger lines + deterministic transaction-id + per-call ledger writes MUST ship together. Phase 3's single fat plan structure is the load-bearing mechanism that enforces this.
</domain>

<decisions>
## Implementation Decisions

### Phase shape & wave structure

- **D-01:** Single fat plan covering all 15 requirements. ONE `03-01-PLAN.md` ships the entire migration atomically. Pro: enforces PITFALLS Pitfall 8 by construction; partial adoption is impossible. Con: large plan (estimated 10-15 tasks), single executor run is longer. Acceptable because the alternative (multi-plan split) introduces a strict serial-wave constraint anyway (every plan touches `hermes-report.sh`) and adds the risk of mid-migration state if execution interrupts between plans.
- **D-02:** The plan MUST be structured so the executor commits in a logical sequence where intermediate commits leave the system in a working state — even though "working state" here means the no-marker fallthrough path (CRON-07) is the last invariant to break. The order is: (1) `split_strategies.py` + unit tests, (2) `cron.lock` declaration in `common.sh`, (3) `hermes-report.sh` marker reader + per-session loop refactor (still using legacy single-call path), (4) per-marker emission + v2 ledger writes + extended transaction-id (cuts over to v2 path), (5) zero-marker fallthrough + fail-open tolerance (CRON-07, TAX-05, MARK-04), (6) `references/setup.md` S2 bias framing, (7) test fixtures (TEST-03 conservation, TEST-04 synthetic bias). Each commit must keep the test suite green.

### Pluggable split seam (CRON-09)

- **D-03:** A new standalone Python module ships at `skills/revenium/scripts/split_strategies.py` (NOT a heredoc). The module exposes a single function `def equal_split(delta_fields: dict, n_markers: int) -> list[dict]` that returns N dicts whose per-field values sum exactly to the input dict's per-field values. Conservation invariant lives in the function itself (last marker absorbs the remainder).
- **D-04:** `hermes-report.sh` invokes the splitter via Python heredoc + `from split_strategies import equal_split`, NOT via subprocess. The heredoc uses `sys.path.insert(0, str(Path(__file__).parent))` if needed to import from the script's own directory.
- **D-05:** The new file is added to `tests/test_repository.py::test_expected_files_exist`. It is also added to the `bash -n` skip list (it's Python, not bash) and to a new `test_split_strategies_pyflakes` or equivalent stdlib-only static check if practical (otherwise skip — `bash -n` exclusion is enough).
- **D-06:** S3/S4 strategies are explicitly out of scope for Phase 3 — but the module's docstring records the plug-in shape (`def weighted_split(...)`, `def guardrail_estimator_split(...)`) so future authors know the contract without re-architecting.
- **Claude's discretion:** exact signature parameters of `equal_split` (kwargs vs positional, named tuple vs dict return) are planner-level decisions, subject to the conservation invariant being byte-exact.

### Ledger v1→v2 versioning & migration

- **D-07:** v2 format is `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>` (5 colon-separated fields). v1 format is `HERMES:<sid>:<total_tokens>:<ts>` (4 fields). Discrimination is by `len(line.split(':'))` — no version prefix sentinel.
- **D-08:** Reader behavior: a v1 line (4 fields) is parsed as "session reported at this `total_tokens` but with no markers" (CRON-05 verbatim). The reader skips it for marker-aware idempotency purposes (no `muid` set to dedupe against). If the current run finds new markers since this v1 row's `ts`, it emits new v2 rows alongside the legacy v1 line — v1 lines are NEVER deleted or upgraded in place.
- **D-09:** Writer behavior: every new ledger append uses v2 format. The cron NEVER writes a v1-shaped row again. Mixed-format ledger files are expected and supported indefinitely (no migration script).
- **D-10:** A reader test (TEST-03 variant) MUST exercise a ledger fixture containing both v1 and v2 rows for the same session to confirm the field-count discrimination is correct under realistic mixed-state conditions.
- **D-11:** The `<comma_separated_muids>` field is non-empty in v2 (at least one muid per row — never `HERMES:sid:tokens:ts:` with empty tail). The zero-marker fallthrough path (CRON-07) writes its single-call ledger row with `muids = "unclassified-${ts_short}"` or equivalent synthetic placeholder so the field is always populated and discrimination by field count remains reliable.

### Concurrency, tolerance, and S2 bias framing

- **D-12:** `flock(2)` semantics — non-blocking + exit 0 with `warn`-level log on contention. The exact command is `flock --nonblock --exclusive 9` (or equivalent `python3 -c "fcntl.flock(...)"` if bash flock is unavailable on macOS). On contention, the cron emits `WARN: prior tick still active, skipping this minute` and exits 0 so the cron daemon doesn't mail a non-zero status (CRON-08).
- **D-13:** `cron.lock` path is declared in `skills/revenium/scripts/common.sh` as `LOCK_FILE="${REVENIUM_STATE_DIR}/cron.lock"`. NOT hardcoded in `hermes-report.sh` or `cron.sh`. `tests/test_repository.py::test_runtime_paths_are_hermes_native` is extended to assert the variable's presence (matches PATH-01/PATH-02 pattern).
- **D-14:** TAX-05 (missing/malformed taxonomy) tolerance lives in the **per-session loop**, NOT in a global preflight. Each session that needs a taxonomy lookup catches `JSONDecodeError`/`FileNotFoundError`, logs a `warn`, and falls through to `--task-type unclassified` for that session only. Other sessions in the same cron run are unaffected.
- **D-15:** MARK-04 (torn last JSON line) tolerance also lives in the **per-session loop**. The marker reader iterates lines in `${MARKERS_DIR}/<sid>.jsonl`; each line is parsed in a try/except. A `JSONDecodeError` on any single line (including the last torn one) logs a `warn` and skips that line. The reader continues to the next line. A session whose entire marker file is corrupt (zero parseable lines) falls through to the CRON-07 single-call path with `--task-type unclassified`.
- **D-16:** S2 bias framing in `skills/revenium/references/setup.md` — ship the PITFALLS one-directional framing verbatim: "GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound, not an estimate. The S2 equal-split is intentionally simple and biases attribution toward classification overhead in mixed windows. Later strategies (S3 weighted, S4 guardrail-estimator) are deferred to v2." Explicitly supersedes the PROJECT.md "bias self-cancels over many windows" framing. STATE.md open question is resolved by this decision; PROJECT.md should be updated in a Phase 5 doc-housekeeping pass (NOT in scope here).
- **D-17:** TEST-04 (synthetic bias test) is shipped in this phase per CRON-09 / Pitfall 5. The test constructs a fixture window with 1 large work-turn marker (e.g., 8,000 tokens delta) + 1 small GUARDRAIL classification-turn marker (e.g., 300 tokens delta) and asserts the cron's S2 output ratio is exactly 50/50 — i.e., pins the known bias rather than hiding it. The test name SHOULD include "bias" in its method name so future contributors can grep for the contract.
- **D-18:** Telemetry log line for S2 bias — every cron tick emits `INFO: S2: window=<n_markers>, mean_per_marker=<delta/n>` per session per tick. When `n_markers == 2 AND any marker has operation_type=GUARDRAIL`, additionally emit `WARN: S2: classification-dominated window, attribution may be lossy`. Log line text is locked-down (operator-debuggable by grep).

### Claude's Discretion

- Exact wording of `warn`/`info` log lines (beyond the locked phrases above) is at the planner/executor's discretion subject to keeping them grep-friendly and timestamped via the existing `info`/`warn`/`error` helpers in `common.sh`.
- Exact byte-exact algorithm for the equal-split remainder absorption (e.g., distribute remainder to last marker only vs round-robin to first K markers) — planner's choice subject to the conservation invariant (`sum(splits) == input_delta` byte-exact).
- Exact field-name conventions inside `split_strategies.equal_split`'s input/output dicts (e.g., `input_tokens` vs `input`, `cache_read_tokens` vs `cache_read`) — planner picks one and threads it consistently; the existing `hermes-report.sh` field names are the natural starting point.
- Exact location of the `## How attribution works` section within `references/setup.md` (top, middle, end) — planner's choice.
- Whether to add a `test_split_strategies_module` or roll the splitter tests into the existing `tests/test_repository.py` — planner's call.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project canonical
- `.planning/PROJECT.md` — Decisions 1-9 (per-turn granularity, agent self-classification, controlled vocabulary, marker file IPC, S2 equal split, --operation-type GUARDRAIL convention, --task-type unclassified default, classify substantive turns only, taxonomy growth)
- `.planning/REQUIREMENTS.md` — TAX-05, MARK-04, CRON-01..09, COMPAT-02, COMPAT-03, TEST-03, TEST-04 (15 IDs total for this phase)
- `.planning/ROADMAP.md` — Phase 3 section with 5 success criteria, especially SC4 (flock exit-cleanly wording) and SC5 (synthetic-bias fixture)
- `.planning/STATE.md` — Phase 2 carry-forwards: HERMES_SESSION_ID = env var with pseudo-id fallback, MARK-04 + TAX-05 reassigned to Phase 3, S2 bias framing discrepancy flagged for resolution here (D-16 above)

### Pitfalls (load-bearing)
- `.planning/research/PITFALLS.md` — Pitfall 5 (S2 bias is one-directional, NOT self-cancelling — informs D-16, D-17, D-18) and Pitfall 8 (per-marker ledger + deterministic transaction-id + per-call writes MUST ship together — informs D-01, D-07..D-11)

### Phase 2 deliverables (consume directly)
- `skills/revenium/task-taxonomy.json` — Read by the per-session loop for label validation (TAX-05 tolerance applies). 8 seed labels.
- `skills/revenium/references/task-taxonomy.md` — Cold-path reference. Atomic-write pattern is the agent's responsibility; the cron is read-only on this file.
- `skills/revenium/SKILL.md` (lines 279-418) — `## FINAL ACTION — TASK CLASSIFICATION` section defines the marker schema the cron will parse. Marker fields: `{muid, ts, sid, task_type, operation_type}` required; `{turn_seq, agent, trace_id, model}` optional. < 1024 bytes per line. `muid` regex `^[0-9a-f]{33}$`.
- `skills/revenium/references/halt-survivability.md` — Operator runbook; informs the SC1 release gate for Phase 2 but does NOT affect Phase 3 implementation directly.

### Phase 1 deliverables (consume directly)
- `skills/revenium/scripts/common.sh` — Source for `STATE_DIR`, `MARKERS_DIR`, `TAXONOMY_FILE`, `LEDGER_FILE`, `STATE_DB`. Phase 3 adds `LOCK_FILE` per D-13.

### Codebase context (read for patterns)
- `skills/revenium/scripts/hermes-report.sh` — Existing reporter, lines 41-268. The per-session loop is what Phase 3 extends. Python heredoc style at lines ~90, 115-165, 179, 216-251. Array-built CLI argv at lines 216-249 is the canonical pattern for adding per-marker flags.
- `skills/revenium/scripts/budget-check.sh` — Python heredoc style analog (lines 43-93). Atomic-write pattern via `tempfile.NamedTemporaryFile` + `os.rename`.
- `tests/test_repository.py` — Existing test class. New tests (TEST-03 conservation, TEST-04 synthetic bias) follow the same stdlib-unittest style. The `bash -n` syntax check (line 60-65) will need to exclude the new `split_strategies.py` file (it's Python).

### Research gates (informational; NOT blocking for plan kickoff)
- **Revenium server-side `--operation-type` default behavior** — `manage_metering` MCP tool query. If `--operation-type` absence differs from explicit `CHAT` in cost calculations, that's a Phase 4 (WIRE-01) concern, NOT a Phase 3 blocker. Phase 3 plans should NOT emit `--operation-type CHAT` for non-GUARDRAIL markers — Phase 4 owns that decision. The researcher should surface this finding so the planner knows what NOT to wire in Phase 3.

</canonical_refs>

<specifics>
## Specific Ideas

- **Ledger v2 fixture for tests:** Both TEST-03 and the v1/v2 discrimination test need ledger fixtures. Use Python heredoc to write fixtures inline in the test class (matches existing `tests/test_repository.py` style — no external fixture data files).
- **Transaction-id length sanity check:** `${sid}-${total_tokens}-${muid}` could exceed reasonable lengths. `sid` is typically ~32-64 chars, `total_tokens` ~6 digits, `muid` is exactly 33 chars per Phase 2 spec. Total ~75-105 chars, well within any sane CLI flag length limit. No truncation needed.
- **Synthetic state.db fixture:** Phase 3 test fixtures need a fake `~/.hermes/state.db` SQLite file. Build it inline via Python heredoc + `sqlite3.connect(':memory:')` plus dumping to a temp file, mirror the real schema's `sessions` table columns (`session_id`, `model`, `billing_provider`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost`, `total_tokens`, `updated_at`).
- **Synthetic markers fixture:** Tests need synthetic marker files. Write them to a temp directory (`tempfile.TemporaryDirectory`) with the JSONL shape Phase 2's TEST-01 already pins.

</specifics>

<deferred>
## Deferred Ideas

- **S3 (weighted) and S4 (guardrail-estimator) split strategies** — already deferred to v2 per PROJECT.md decision 5. Phase 3 ships the pluggable seam so they can drop in later (CRON-09 + D-06).
- **PROJECT.md "bias self-cancels" cleanup** — D-16 resolves the framing discrepancy in `references/setup.md` but does NOT touch PROJECT.md itself. Defer the PROJECT.md update to Phase 5 (housekeeping pass) so Phase 3 doesn't churn project-level docs mid-flight.
- **Ledger migration script** — D-09 explicitly says no migration; v1 lines stay in place forever. If at some future point the team wants to clean up v1 rows, that's a separate one-shot cleanup script outside this project's scope.
- **Per-tick metering log line for non-bias cases** — D-18 logs `INFO: S2: window=N, mean_per_marker=X` per session per tick. If this turns out to be too noisy, a follow-up phase can add a verbosity flag or sampling. Phase 3 ships the noisier version (operator-debuggable by default).
- **Telemetry export of bias warnings** — D-18's WARN log line is local-only. Sending the bias warning to Revenium as a side-channel event is deferred indefinitely (out of scope for v1).

</deferred>

---

*Phase: 03-cron-marker-reader-equal-split-ledger-v2*
*Context gathered: 2026-05-12 via /gsd-discuss-phase*
