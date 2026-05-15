# Milestones

## v1.0 — Task-Type Metering (Shipped: 2026-05-15)

**Phases:** 6 | **Plans:** 14 | **Tasks:** 64 | **Tests:** 0 → 45 | **Timeline:** 2026-05-12 → 2026-05-15 (4 days)

### Delivered

Every metered completion that leaves the `revenium` Hermes skill carries an accurate, content-driven `--task-type` and `--operation-type` to Revenium analytics — flipping spend attribution from undifferentiated per-session totals to per-turn activity breakdowns.

### Key accomplishments

1. **Path discipline foundation** (Phase 1) — `TAXONOMY_FILE` + `MARKERS_DIR` declared in `common.sh` as the single source of truth; `chmod 700` on marker dir; path-discipline test continues to fail any drift.

2. **Agent-side marker contract** (Phase 2) — `## FINAL ACTION — TASK CLASSIFICATION` block appended to `SKILL.md` with substantive-turn rule + 4 canonical examples + trivial blocklist; seed `task-taxonomy.json` shipped; marker schema pinned by `test_marker_file_schema`; halt-check survivability runbook surfaced in README.md.

3. **Cron-side split pipeline** (Phase 3) — marker-aware split path emits N `revenium meter completion` calls with byte-exact field-sum conservation across splits, extended `--transaction-id` shape (`${sid}-${total_tokens}-${muid}`), 5-field ledger row, `flock(2)` lockfile preventing concurrent reads, pluggable split-strategy architecture.

4. **Wire enrichment** (Phase 4) — argv now carries the richest available `--operation-type`, `--agent`, `--trace-id` per marker with colon-dash fallbacks to today's hardcoded values; `--operation-type CHAT` on zero-marker fallthrough (D-22 gate discharged); 8-provider regression pinned across anthropic/openai/google/xai/deepseek/meta/openrouter-special/bedrock-special.

5. **Mechanical classification** (Phase 6) — in-process `hermes_cli` plugin registered on `on_session_end` that writes a GUARDRAIL+CHAT marker pair for every `run_conversation()` exit — universal session coverage independent of agent self-classification, with state.db subagent inheritance via `parent_session_id`, budget-halt gating, and SKILL.md FINAL ACTION double-write avoidance.

6. **Classifier chain unlock** (3 quick tasks, 2026-05-14) — three live-environment hotfixes shipped same-day in response to Mac Studio diagnostic chain:
   - **260514-n8e** removed broken D-07 trivial-skip (predicate degenerated to `tool_count==0` because plugin always passed `response=None`; ~94% of cron sessions were silently dropped).
   - **260514-nfb** rewrote `_build_classification_prompt` to bias the LLM toward minting specific descriptive labels rather than reusing bland seed labels.
   - **260514-nz8** added `_read_session_messages` so the LLM finally sees actual session content from `state.db.messages` instead of empty strings.
   First content-driven labels (`moltbook_heartbeat_check`, `hardware_overview`) reached Revenium dashboards immediately after deployment.

7. **Operational hygiene** (Phase 5) — `prune-markers.sh` (operator-invoked, ledger-based staleness, 30-day default + env override, dry-run, info-helper logging); classifier mint-back persists newly-minted labels to `task-taxonomy.json` with recency-ordered prompt; Phase 4 review WRs (pipe-safety sanitize, dead-var removal, test env isolation) closed; PROJECT.md decisions D-3 and D-8 rewritten in place + Evolution Notes section.

### Known deferred items at close

6 audit items acknowledged (see STATE.md `## Deferred Items`): all are documentation hygiene or false-positive audit flags, not production gaps. v1.0 has been live-verified end-to-end on Mac Studio (`ssh 172.16.1.175`):
- prune-markers.sh operator UAT (5/5 passing on bash 3.2.57)
- classifier producing varied content-driven labels reaching Revenium
- Phase 4 wire shipping `--operation-type CHAT` on every call

Tech debt carried to v1.1:
- `_persist_label_to_taxonomy` lacks `fcntl.flock` (mint-back race window)
- `clear-halt.sh` uses same `${VAR@Q}` bash 4.4+ syntax that broke prune-markers (DEFERRED-CLEAR-HALT-BASH-32)
- `REVENIUM_MARKER_RETENTION_DAYS=0` not validated (DEFERRED-RETENTION-MIN-VALIDATION)
- Dead `_count_tools_in_current_turn` helper kept per D-37 deferred
- Phase 02 + Phase 03 verification/UAT status flags stale (overtaken by Phase 4/5/6 live verification)

See `.planning/milestones/v1.0-ROADMAP.md` and `.planning/milestones/v1.0-REQUIREMENTS.md` for the full historical record.

---
