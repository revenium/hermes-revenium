# Requirements: Hermes-Revenium Task-Type Metering

**Defined:** 2026-05-12
**Core Value:** Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session.

## v1 Requirements

Requirements for the initial release. Each maps to roadmap phases. Drawn from PROJECT.md Active items and the research bundle (`.planning/research/`).

### Paths & Path Foundation

- [ ] **PATH-01**: `scripts/common.sh` declares `TAXONOMY_FILE` and `MARKERS_DIR` under `~/.hermes/state/revenium/` as the single source of truth — no other script inlines these paths
- [ ] **PATH-02**: Install / setup helpers create `MARKERS_DIR` with `chmod 700` for defense-in-depth on session marker files (which can contain user-visible task descriptions)
- [ ] **PATH-03**: `test_runtime_paths_are_hermes_native` is extended to assert `TAXONOMY_FILE` and `MARKERS_DIR` strings appear in `common.sh` and use `.hermes` / `state/revenium`

### Taxonomy

- [ ] **TAX-01**: A seed `task-taxonomy.json` ships with the skill containing 6–8 starting labels drawn from the OpenLLMetry RFC #3460 (`research`, `analysis`, `generation`, `review`) plus Hermes-flavored extensions (`refactor`, `planning`, `debugging`, `code_review`)
- [ ] **TAX-02**: The taxonomy file is a single JSON object with allow-listed top-level keys (label → `{description, examples}`); a documented schema lives in `references/task-taxonomy.md`
- [ ] **TAX-03**: All labels in the taxonomy match the regex `^[a-z][a-z0-9_]{1,47}$` (lowercase, snake_case, length-bounded) — enforced cron-side at read time, not just by the agent's prompt
- [ ] **TAX-04**: The agent updates the taxonomy via write-to-tmp + `os.rename` under `fcntl.flock` so a concurrent reader never sees a partial file
- [ ] **TAX-05**: The cron tolerates a missing or malformed taxonomy file by falling through to the `unclassified` path with a warning logged — taxonomy corruption does not break metering

### Marker Contract

- [ ] **MARK-01**: The agent appends one JSONL line per substantive turn to `~/.hermes/state/revenium/markers/<session_id>.jsonl`, written with a single `write(2)` to a file opened in append mode
- [ ] **MARK-02**: Each marker record is < 1024 bytes and contains at minimum `{muid, ts, sid, task_type, operation_type}`; optional fields are `turn_seq`, `agent`, `trace_id`, `model`
- [ ] **MARK-03**: Marker `muid` is a ULID (lexicographically sortable by time) so the cron can read-forward from a stored timestamp without scanning the whole file
- [ ] **MARK-04**: Cron reader tolerates a torn last line (incomplete JSON) by ignoring it and resuming on the next tick
- [ ] **MARK-05**: Marker records never contain free-form user prompts or assistant responses — only structured fields from the allow-list. Privacy boundary is enforced by the marker schema

### Skill Prompt (SKILL.md classification block)

- [ ] **PROMPT-01**: The new classification block in `SKILL.md` is end-loaded (after the existing halt-check) so it never displaces the load-bearing budget-halt instructions
- [ ] **PROMPT-02**: `SKILL.md` defines "substantive turn" with a static blocklist of trivial labels (`ack`, `greeting`, `confirm`, etc.) plus 2–3 canonical positive examples
- [ ] **PROMPT-03**: The classification block instructs lookup-first: read `task-taxonomy.json`, reuse an existing label if any fits, only mint a new label when none does — and stipulates lowercase snake_case
- [ ] **PROMPT-04**: The classification turn itself is metered as `--operation-type GUARDRAIL` via a marker the agent emits for the classification work
- [ ] **PROMPT-05**: Marker write is the FINAL ACTION in the new block (per Anthropic context-engineering guidance) — easiest step to skip, placed where it's hardest to overlook
- [ ] **PROMPT-06**: A `references/task-taxonomy.md` document carries the long-form details (schema, examples, normalization rules) so `SKILL.md` stays compact
- [ ] **PROMPT-07**: A prompt-invariant test asserts that the existing halt-block phrasing (`ABSOLUTE FIRST — NON-NEGOTIABLE` or equivalent contractual string) still appears in `SKILL.md` before the new classification block

### Cron Split + Ledger Migration

- [ ] **CRON-01**: `hermes-report.sh` reads markers since the previous ledger row's `ts` for each session, skipping any `muid` already recorded in the prior row
- [ ] **CRON-02**: Per session delta, the cron splits `input/output/cache_read/cache_write/cost/total` equally across N markers, with the remainder absorbed by the last marker so summed splits exactly equal the input delta (conservation invariant)
- [ ] **CRON-03**: One `revenium meter completion` call is emitted per marker with that marker's `--task-type` and `--operation-type`, plus the per-split numeric fields
- [ ] **CRON-04**: `--transaction-id` is extended to `${sid}-${total_tokens}-${muid}` so Revenium server-side dedupe catches retries even if the local ledger is lost
- [ ] **CRON-05**: Ledger row format extends to `HERMES:<sid>:<total_tokens>:<ts>:<comma_separated_muids>`; legacy 4-field rows remain readable (parsed as "no markers reported yet for this delta")
- [ ] **CRON-06**: Ledger writes happen per-call (not per-batch) so a partial multi-call failure leaves a recoverable state on the next tick
- [ ] **CRON-07**: When `N == 0` markers exist for a session delta (older install, agent didn't classify, missing file), the cron falls through to the existing single-call path with `--task-type unclassified` and no explicit `--operation-type`
- [ ] **CRON-08**: A file-lock (`flock(2)`) on `~/.hermes/state/revenium/cron.lock` prevents overlapping cron ticks from racing on the ledger
- [ ] **CRON-09**: The split strategy is invoked through a pluggable seam (a single function or Python class) so S3 (weighted) or S4 (guardrail-estimator) can drop in later without touching the cron's outer loop

### Wire Enrichment (Adjacent-Flag Wins)

- [ ] **WIRE-01**: `--operation-type` defaults to `CHAT` on non-guardrail work markers (drawn from OpenInference span_kind vocabulary) — only after verifying via the Revenium `manage_metering` tool that this does not change cost calculations for existing users
- [ ] **WIRE-02**: `--agent` is populated from the marker's `agent` field if present (e.g., the slash-command or skill name); falls back to `"Hermes"` for backward compatibility
- [ ] **WIRE-03**: `--trace-id` is populated from the marker's `trace_id` if present; falls back to `${sid}` for backward compatibility
- [ ] **WIRE-04**: Each split call carries the same provider/model/source values as the legacy single-call path (provider inference, cost scaling, OpenRouter/Bedrock special-casing) — no provider regressions

### Backward Compatibility & Invariants

- [ ] **COMPAT-01**: Existing installs without markers continue to meter exactly as before, differing only in carrying `--task-type unclassified` on the wire (verified via byte-by-byte argv diff against current behavior)
- [ ] **COMPAT-02**: A conservation test pins `sum(split_calls.numeric_fields) == input_delta.numeric_fields` for every supported split width
- [ ] **COMPAT-03**: Re-running the cron after any partial failure never double-reports an `(sid, muid)` pair to Revenium (re-run audit test)
- [ ] **COMPAT-04**: The existing skill frontmatter contract (`name: revenium`, `metadata.hermes`, `category: devops`) is preserved — `test_skill_frontmatter_has_hermes_metadata` continues to pass

### Test Coverage

- [ ] **TEST-01**: Repo invariant tests cover the marker file schema (allow-listed keys, < 1024-byte size, lowercase snake_case `task_type`)
- [ ] **TEST-02**: Repo invariant tests cover the taxonomy file schema (allow-listed top-level keys, label regex, no forbidden labels)
- [ ] **TEST-03**: A cron-behavior test fixture (synthetic state.db + synthetic marker file) verifies equal-split conservation, fallthrough on N==0, and idempotency under simulated partial failure
- [ ] **TEST-04**: A synthetic-bias test pins the documented S2 attribution behavior (small classification turn + large work turn → 50/50) so the known bias direction is explicit, not hidden
- [ ] **TEST-05**: `test_no_legacy_branding_left` continues to pass for any new content; the project does NOT scrub pre-existing offenders in `.planning/codebase/*.md` (those are tracked separately)

## v2 Requirements

Deferred to future release. Acknowledged but not in v1 roadmap.

### Smarter Attribution

- **V2-01**: S3 weighted split — markers carry an agent-estimated `length_hint`; cron proportions deltas accordingly. Trigger: Revenium-side attribution drifts noticeably in practice.
- **V2-02**: S4 GUARDRAIL estimator — separate pass subtracts an estimated guardrail share before splitting work share. Trigger: GUARDRAIL ends up oversized enough to distort work-vs-overhead reporting.

### Operator Tooling

- **V2-03**: `tools/audit-taxonomy.py` groups labels by normalized + stemmed form and proposes merges for near-duplicates
- **V2-04**: `scripts/show-recent-markers.sh <session_id>` debug helper prints the last N markers for a session in human-readable form
- **V2-05**: Cron-side telemetry log lines for "tokens reported but no markers" and "classification-dominated window"

### Housekeeping

- **V2-06**: `scripts/prune-markers.sh` removes marker files for sessions whose latest-reported ledger row is older than N days
- **V2-07**: Closed-session rotation — marker files for ended sessions get renamed to `.closed` after a configurable grace period

## Out of Scope

Explicit exclusions. Each is a feature competing products ship that this project deliberately rejects.

| Feature | Reason |
|---------|--------|
| Modifying Hermes' `state.db` schema or upstreaming per-turn columns | We don't own Hermes; this project lives inside what the skill can observe |
| Real-time / mid-turn metering | Per-cron-cycle attribution (~60s lag worst case) is the documented contract; synchronous metering rejected on complexity |
| Per-turn token exactness | S2 equal-split is the accepted approximation; S3/S4 deferred to v2 |
| Retroactive classification of historical sessions | Only forward-going turns get classified; no backfill |
| Cross-session task IDs / multi-session task threading | Markers scoped to a single Hermes session |
| Server-side taxonomy curation on Revenium | Taxonomy lives locally per host; Revenium's normalization is its concern |
| LLM-as-judge backfill of unclassified turns | Adds an extra LLM dep + privacy boundary; rejected for v1 |
| SDK call-site decorators or HTTP gateway headers | Hermes has no synchronous SDK seam to hook; would require modifying user agent code we don't own |
| Free-form `operation_type` values outside the Revenium enum | Revenium enforces a 17-value enum; honor the contract |
| Heavy observability frameworks (OTel SDK, OpenLLMetry SDK, Pydantic) | No new runtime deps — stdlib Python + Bash is the constraint |

## Traceability

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (Empty until roadmap creates phases) | — | Pending |

**Coverage:**
- v1 requirements: 37 total
- Mapped to phases: 0 (populated by roadmap)
- Unmapped: 37 ⚠️ (expected pre-roadmap)

---
*Requirements defined: 2026-05-12*
*Last updated: 2026-05-12 after initial definition*
