# Roadmap: Hermes-Revenium Task-Type Metering

**Project:** Brownfield extension to the `revenium` Hermes skill adding per-turn task attribution.

Every metered completion that leaves this skill carries an accurate, consistently-spelled `--task-type` so Revenium analytics group spend by what the agent actually did, not just by session.

## Milestones

- ✅ **v1.0 — Task-Type Metering** (shipped 2026-05-15) — see [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- 📋 **v1.1 — TBD** (next milestone — run `/gsd-new-milestone` to define scope)

## Phases

<details>
<summary>✅ v1.0 Task-Type Metering (Phases 1-6) — SHIPPED 2026-05-15</summary>

- [x] Phase 1: Path Foundation (1/1 plans) — completed 2026-05-12
- [x] Phase 2: Prompt Design & Marker Contract (3/3 plans) — completed 2026-05-12
- [x] Phase 3: Cron Marker Reader + Equal-Split + Ledger v2 (1/1 plans) — completed 2026-05-13
- [x] Phase 4: Wire Enrichment (1/1 plans) — completed 2026-05-14, verified via UAT 5/5
- [x] Phase 5: Housekeeping & Compat Hardening (4/4 plans) — completed 2026-05-15, verified via live Mac Studio operator UAT
- [x] Phase 6: Mechanical Classification via Hermes agent:end Hook (4/4 plans) — completed 2026-05-14, verified via UAT round 4

Plus 3 quick tasks shipped 2026-05-14 in response to live Mac Studio diagnostic chain (D-07 removal, mint-first prompt rewrite, state.db content lookup). See `.planning/STATE.md` Quick Tasks Completed section + `.planning/quick/` for details.

Full detail: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
Requirements: [milestones/v1.0-REQUIREMENTS.md](./milestones/v1.0-REQUIREMENTS.md)
Summary: [MILESTONES.md](./MILESTONES.md)

</details>

### 📋 v1.1 (planned)

Run `/gsd-new-milestone` to define v1.1 scope. Likely candidates from v1.0 deferred items:

- Add `fcntl.flock` to `_persist_label_to_taxonomy` (mint-back race window)
- Fix `${VAR@Q}` bash 4.4+ syntax in `clear-halt.sh` (latent broken on macOS stock bash 3.2)
- Validate `REVENIUM_MARKER_RETENTION_DAYS >= 1` in `prune-markers.sh`
- Remove dead `_count_tools_in_current_turn` helper (carried per D-37)
- Optional `install-prune-cron.sh` opt-in installer
- Trash-recovery option for `prune-markers.sh` instead of straight `rm`

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Path Foundation | v1.0 | 1/1 | Complete | 2026-05-12 |
| 2. Prompt Design & Marker Contract | v1.0 | 3/3 | Complete | 2026-05-12 |
| 3. Cron Marker Reader + Equal-Split + Ledger v2 | v1.0 | 1/1 | Complete | 2026-05-13 |
| 4. Wire Enrichment | v1.0 | 1/1 | Verified | 2026-05-14 |
| 5. Housekeeping & Compat Hardening | v1.0 | 4/4 | Verified | 2026-05-15 |
| 6. Mechanical Classification via agent:end Hook | v1.0 | 4/4 | Verified | 2026-05-14 |
