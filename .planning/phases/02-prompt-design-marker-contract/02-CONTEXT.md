# Phase 2: Prompt Design & Marker Contract - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 ships the agent half of the agent ↔ cron marker contract. Concretely:

1. **`SKILL.md` extension** — an end-loaded `FINAL ACTION — TASK CLASSIFICATION` section that defines the substantive-turn hard rule, ships 4 canonical examples, documents the trivial-label blocklist, and pins one canonical marker-write snippet.
2. **Seed `task-taxonomy.json`** — 8 starting labels with `{description, examples}` per label.
3. **`references/task-taxonomy.md`** — schema, label-by-label catalog, normalization rules.
4. **Marker schema** — allow-listed JSONL record shape, < 1024 bytes, ULID `muid`.
5. **Manual halt-survivability E2E test plan** at `references/halt-survivability.md` (the Phase 2 research flag).
6. **Repo invariant tests** for marker schema (TEST-01) and taxonomy schema (TEST-02), and a prompt-invariant test (PROMPT-07) that the halt-block phrasing still appears before the new classification block.

The single load-bearing constraint: the existing `ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` anchor must stay unambiguously dominant in long sessions after the new content is added. The classification block is closing discipline; the halt-check is opening discipline; they share the file but not the priority anchor.

Out of scope this phase: any cron behavior change (Phase 3 owns marker reading / split / ledger v2), wire enrichment (Phase 4), housekeeping (Phase 5).

</domain>

<decisions>
## Implementation Decisions

### Halt-Survivability E2E Test Plan (Phase 2 research flag)
- **D-01:** Two session-length scenarios: a short baseline (~2k tokens of prior context) and a long session (~20k tokens). Captures both fresh-load behavior and the context-dilution failure mode without ballooning tester time.
- **D-02:** Two model families: one Anthropic (Claude Sonnet 4.6 — Hermes default) and one OpenAI (GPT-4o-class). Covers vendor-skew without forcing a three-vendor matrix for v1.
- **D-03:** Pass criterion is strict — after flipping `budget-status.json` to `halted: true`, the very next agent turn must emit the contractual halt string **verbatim** and call **no tools**. Any deviation = FAIL. No retry budget. Matches the existing SKILL.md "ABSOLUTE FIRST" absolute framing.
- **D-04:** Test plan lives at `skills/revenium/references/halt-survivability.md`; operator runs it manually before each release. The plan is surfaced in `CLAUDE.md` and `README.md` so future contributors can't silently skip it.

### Seed Taxonomy
- **D-05:** Both `review` (general) and `code_review` (specific) ship as separate seed labels. Lets analytics distinguish code-PR review from design-doc / planning-doc review without forcing the agent to choose at write time.
- **D-06:** Final seed list (8 labels, in the exact order they ship in `task-taxonomy.json`): `research`, `analysis`, `generation`, `review`, `code_review`, `refactor`, `planning`, `debugging`. Four from the OpenLLMetry RFC #3460 (`gen_ai.task.type` draft) + four Hermes-flavored extensions. Matches REQUIREMENTS.md PATH-01 example list.
- **D-07:** Per-label schema is `{description: string, examples: array}`. Matches REQUIREMENTS.md TAX-02 verbatim. Examples support the lookup-first reuse discipline — the agent reads them when deciding whether an existing label fits the current turn's semantics.
- **D-08:** Mint policy is **lookup-first, reuse aggressively, mint only when no existing label clearly fits**. Aligns with PROJECT.md decision 3. The agent does NOT mint on every borderline case; bias toward reuse — fragmentation is permanent, oversized labels are recoverable.

### Substantive-Turn Hard Rule (PITFALLS Pitfall 2 mitigation)
- **D-09:** The hard rule shipped in SKILL.md is verbatim PITFALLS-recommended: *"Classify the turn if ANY of: (a) you called a tool other than read-only file inspection; (b) you produced > 200 words of new content; (c) the user asked a question requiring multi-step reasoning. Skip the turn if your entire output is ≤ 2 sentences and called no tools."*
- **D-10:** 4 canonical examples ship inline in `SKILL.md`: 2 clear (one obvious substantive — code review with tool calls; one obvious trivial — single-line clarification) + 2 borderline (one that **should** classify — 5-paragraph explanation, no tools; one that should **not** classify — multi-line greeting). Anthropic context-engineering guidance is canonical-examples-over-rule-lists; we ship both.
- **D-11:** When the agent is uncertain about a borderline turn, the documented behavior is **skip — do not write a marker**. The cron will fall back to `--task-type unclassified` and meter the tokens against the catch-all bucket. Under-classification is recoverable; over-classification permanently pollutes the taxonomy.
- **D-12:** Trivial-label blocklist (documented in SKILL.md, cron-enforced in Phase 3): `ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks`. Cron rejects markers carrying any of these `task_type` values. The blocklist is closed-set for v1; new entries require a release.

### SKILL.md Section + Reference-Doc Split
- **D-13:** Insertion site: **after the existing `## Verification` section, as the final section in `SKILL.md`**. Maximally end-loaded. The halt-check anchor (`ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)`) keeps its first-section position; the classification block becomes the closing-discipline counterpart.
- **D-14:** Section heading: `## FINAL ACTION — TASK CLASSIFICATION`. Closing-discipline framing intentional. The block deliberately does **not** use `ABSOLUTE`, `FIRST`, or `NON-NEGOTIABLE` — those words remain reserved for the halt-check so the priority anchor isn't diluted.
- **D-15:** Content split:
  - `SKILL.md` (hot path — read every turn): hard rule, 4 canonical examples, trivial blocklist, exactly one canonical marker-write Python snippet.
  - `references/task-taxonomy.md` (cold path — read on demand): full schema description, label-by-label `{description, examples}` catalog, normalization rules (lowercase + snake_case enforcement, length bounds, regex), guidance on when to mint a new label vs reuse.
- **D-16:** Canonical marker-write snippet uses a **Python heredoc**, mirroring the existing cron-side `hermes-report.sh` pattern. The snippet opens `${MARKERS_DIR}/<session_id>.jsonl` in append mode, dumps a single-line JSON record with the trailing newline, and is the ONLY snippet the agent should be following. Lets the agent reuse `ulid` / `fcntl` stdlib idioms if it wants stronger atomicity, without forcing a second-language context switch.

### Claude's Discretion
- The exact wording of the 4 canonical examples (concrete code review / clarification / explanation / greeting transcripts) is left to the planner/executor — the rule above pins shape, count, and balance; specific text is implementation-level.
- The exact wording of each seed-label `description` field (e.g., what "research" vs "analysis" means in practice) is left to the planner/executor, subject to the constraint that descriptions are crisp enough that the agent can apply the lookup-first rule without re-asking the user.
- The exact section structure of `references/task-taxonomy.md` (subsection ordering, formatting) is left to the planner/executor.
- The exact prompt-invariant test wording for PROMPT-07 is left to the planner/executor — must assert that `ABSOLUTE FIRST — HALT CHECK (NON-NEGOTIABLE)` substring (or the agreed contractual equivalent) appears in SKILL.md AND that its position is earlier in the file than the new `FINAL ACTION — TASK CLASSIFICATION` section heading.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — TAX-01..05, MARK-01..05, PROMPT-01..07, TEST-01..02 (Phase 2 requirements, verbatim acceptance language).
- `.planning/ROADMAP.md` §"Phase 2" — Phase 2 success criteria + the research-flag note for the halt-survivability test plan.
- `.planning/PROJECT.md` — Key Decisions 1, 2, 3, 4, 6, 7, 8, 9 (all carry-forward and locked).

### Research bundle (HIGH-leverage for this phase)
- `.planning/research/SUMMARY.md` — synthesized phase implications + the "Implications for Roadmap" build order this phase implements.
- `.planning/research/PITFALLS.md` — **Pitfalls 2, 6, 7 are the load-bearing ones for Phase 2.** Pitfall 2 is the source of the substantive-turn hard rule. Pitfall 6 is the source of the FINAL ACTION pattern. Pitfall 7 is the halt-check priority constraint.
- `.planning/research/STACK.md` — OpenInference span_kind vocabulary for `--operation-type` (STABLE 1.x, includes `GUARDRAIL`), seed-taxonomy candidates from OpenLLMetry RFC #3460, marker file format (UTF-8 JSONL, `\n` separator).

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` §"Two halves never call each other" — the agent↔cron filesystem-only coupling that markers extend.
- `.planning/codebase/CONVENTIONS.md` — file-format contracts, naming patterns, file-level conventions for SKILL.md.

### Code to extend
- `skills/revenium/SKILL.md` — file being extended; the existing halt-check block (lines 24-46) is the priority anchor the new block must NOT displace.
- `skills/revenium/scripts/common.sh` — Phase 1 ships `TAXONOMY_FILE` and `MARKERS_DIR` here; Phase 2 writes via these variables only.
- `skills/revenium/references/setup.md`, `skills/revenium/references/troubleshooting.md` — existing reference-doc shape; `references/task-taxonomy.md` and `references/halt-survivability.md` ship alongside.
- `tests/test_repository.py` — extended with TEST-01 (marker schema), TEST-02 (taxonomy schema), PROMPT-07 (prompt-invariant ordering assertion).

### Phase 1 hand-off (already shipped)
- `.planning/phases/01-path-foundation/01-01-SUMMARY.md` §"Next Phase Readiness" — confirms `${TAXONOMY_FILE}` and `${MARKERS_DIR}` are resolvable from any script that sources `common.sh`. Phase 2's marker-writing logic MUST write via the variables, never via literals.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`common.sh` path variables (Phase 1 output)**: `${TAXONOMY_FILE}` and `${MARKERS_DIR}` are already declared with the canonical `${REVENIUM_*:-${STATE_DIR}/*}` env-fallback shape. `MARKERS_DIR` is auto-created on every source (mkdir -p multi-target) and hardened to 0700 by `install-cron.sh`. Phase 2 marker-write snippets in SKILL.md must reference `${MARKERS_DIR}/<session_id>.jsonl`, never the literal path.
- **`tests/test_repository.py`** — established pattern for repo invariant tests. New tests for marker schema, taxonomy schema, and prompt invariant should extend this file (same pattern as `test_runtime_paths_are_hermes_native` extension shipped in Phase 1).
- **SKILL.md frontmatter** — `name: revenium`, `metadata.hermes:`, `category: devops` are contractual and tested by `test_skill_frontmatter_has_hermes_metadata`. Phase 2 must NOT modify the frontmatter; new content goes in the body.
- **Python heredoc pattern** in `scripts/hermes-report.sh` — the established way to do stdlib-only JSON / fcntl / ULID work inside the skill. The canonical marker-write snippet in SKILL.md mirrors this pattern.

### Established Patterns
- **Filesystem-only coupling between halves** — agents write marker files; cron reads them. Phase 2 must NOT introduce any synchronous call from SKILL.md to cron scripts or to the Revenium API. This is a hard architectural invariant enforced socially today.
- **State-path discipline** — all new state paths go in `common.sh`; PATH-01/02/03 enforces this for `TAXONOMY_FILE` / `MARKERS_DIR`. The path-discipline test will fail any drift.
- **No-legacy-branding regex** — `test_no_legacy_branding_left` greps every text file for the forked-tool product-name regex on `tests/test_repository.py:47`. All new files (`references/task-taxonomy.md`, `references/halt-survivability.md`, seed `task-taxonomy.json`) must avoid those strings. Verified post-Phase-1: full suite green.
- **Soft-fail vs hard-fail script flags** — preserved as-is. Phase 2 does not touch script flags.

### Integration Points
- **`SKILL.md` body** — between `## Verification` (current last section) and EOF. The new `## FINAL ACTION — TASK CLASSIFICATION` section becomes the new file terminus.
- **`skills/revenium/references/`** — `task-taxonomy.md` and `halt-survivability.md` are new files alongside existing `setup.md` and `troubleshooting.md`.
- **`skills/revenium/`** — `task-taxonomy.json` ships at the skill root (NOT in `state/revenium/`). The seed file is installed; the cron / agent reads the live mutable file at `${TAXONOMY_FILE}` (which `setup-local.sh` / install-cron.sh copies on first install — Phase 2 plan must specify install-time copy behavior).
- **Tests** — `tests/test_repository.py` for the three new tests (TEST-01, TEST-02, PROMPT-07).

</code_context>

<specifics>
## Specific Ideas

- The hard-rule sentence shipped in SKILL.md is preserved verbatim from PITFALLS Pitfall 2 mitigation (D-09). Downstream agents must not paraphrase it — exact wording carries the semantic guarantee.
- The 4 canonical examples mirror the categories in PITFALLS Pitfall 2 mitigation: one clear-substantive (with tools), one clear-trivial (single-line clarification), one borderline-classify (multi-paragraph prose), one borderline-skip (multi-line greeting).
- The trivial blocklist is the verbatim PITFALLS list (D-12). Cron-side enforcement in Phase 3 must use this exact array.
- `task-taxonomy.json` seed file is **8 labels, in the order: research, analysis, generation, review, code_review, refactor, planning, debugging**. The order is not semantic but pins the file to a deterministic byte sequence for tests.

</specifics>

<deferred>
## Deferred Ideas

- **`tools/audit-taxonomy.py`** (V2-03 in REQUIREMENTS.md) — deferred to v2. Group labels by normalized + stemmed form and propose merges for near-duplicates. Trigger: post-launch when fragmentation appears in real data.
- **`scripts/show-recent-markers.sh <session_id>`** (V2-04) — operator debug helper. Deferred to v2.
- **S3 (weighted split) / S4 (GUARDRAIL estimator)** — already deferred per PROJECT.md decision 5; cron split-strategy seam (CRON-09) will be added in Phase 3 as the future pluggable hook.
- **Closed-session marker rotation** (V2-07) — `.closed` suffix rename for ended sessions. Deferred to v2.
- **Aliases array in taxonomy schema** — considered in D-07, rejected for v1 to keep schema minimal. Re-evaluate post-launch if fragmentation forces it.
- **Single-word affirmative blocklist expansion** (`ok`, `yes`, `no`, `sure`, `noted`) — considered in D-12, rejected for v1 to keep the blocklist closed-set. Add post-launch only if Revenium-side data shows these labels appearing.

None of the above is in scope for Phase 2; all are documented here so future phases can pick them up without re-deriving the context.

</deferred>

---

*Phase: 02-prompt-design-marker-contract*
*Context gathered: 2026-05-12*
