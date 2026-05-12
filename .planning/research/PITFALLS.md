# Pitfalls Research

**Domain:** Agent-driven task classification with a controlled vocabulary, layered on a two-half (cron + skill-prompt) metering pipeline
**Researched:** 2026-05-12
**Confidence:** MEDIUM-HIGH — direct domain experience is thin in the literature (the design is somewhat novel), but each component pitfall (controlled-vocabulary drift, JSONL growth, O_APPEND races, idempotency under partial failure, long-context prompt degradation) has well-established prior art that this analysis maps onto the project's specific shape.

The pitfalls below are intentionally specific to: (a) an LLM agent that maintains its own taxonomy file, (b) a marker-file contract between an in-session agent and an out-of-session cron, and (c) the existing ledger-based idempotency model in `hermes-report.sh`. Generic "be careful with AI" warnings are not included.

---

## Critical Pitfalls

### Pitfall 1: Taxonomy fragmentation under nominally-strict lookup-first prompts

**What goes wrong:**
Even with a prompt that says "read the taxonomy first, reuse before minting," the agent emits near-duplicates: `code_review`, `code-review`, `CodeReview`, `review_code`, `reviewing_code`, `code_review_v2`. Over weeks, `task-taxonomy.json` accumulates 40+ labels for what should be 6-8 buckets. Revenium-side analytics fragment: a "spend by task" bar chart shows ten thin bars for code-review-like work instead of one tall one. The Core Value statement in `PROJECT.md` explicitly defines this as feature failure — "If the taxonomy fragments… the feature has failed even if the wire protocol works."

**Why it happens:**
1. LLMs generate from a distribution over tokens, not from a deterministic lookup. "Look up first" is an instruction the model can follow, but a long context (Hermes session) pushes the taxonomy file's contents farther from the active classification turn.
2. Naming-convention pressure: the model has internal preferences (Python contexts → snake_case, JS → camelCase, prose → hyphenated). The taxonomy entry was minted in one mode; the next classification turn happens in a different mode.
3. The agent's "is this label appropriate?" judgment is fuzzy. Two semantically-equivalent prompts can yield different "best match" calls. Without a normalization layer, both calls write.
4. Existing literature on controlled-vocabulary deduplication (see Sources) treats human input as the drift source; agent input has the same problem but at higher throughput.

**How to avoid:**
- **Pre-write normalization (always-on):** Before the agent writes a marker, run a normalization step that lowercases, replaces `-` and spaces with `_`, strips non-`[a-z0-9_]` characters, and collapses runs of `_`. Enforce it server-side (in the cron, before reading markers) so a mis-following agent cannot bypass it.
- **Fuzzy-match in the lookup prompt:** Inject the full taxonomy file into the prompt with each entry on its own line, and instruct the agent: "If your candidate label has Levenshtein distance ≤ 2 from any existing label, OR shares a stemmed root, reuse the existing label." Pair this with a deterministic post-write merger pass.
- **Periodic dedupe pass (offline):** A `tools/dedupe-taxonomy.py` script (stdlib only) that groups labels by normalized form + stem and proposes merges. Run by hand initially; potentially a weekly cron later. Crucially: rewrite historical markers when merging, so Revenium analytics retroactively reflect the merge.
- **Cap the taxonomy size with a soft ceiling.** When the taxonomy hits N entries (say 25), the SKILL.md instruction flips from "mint if no fit" to "reuse the closest existing label, even if imperfect." This is an admission that perfect classification is not the goal; consistent buckets are.
- **Test the invariant:** Add `tests/test_taxonomy_invariants.py` asserting every key in `task-taxonomy.json` matches `^[a-z][a-z0-9_]{1,31}$`. Run on a checked-in fixture; if the agent's real taxonomy diverges, that's a debugging signal, not a test failure.

**Warning signs:**
- Taxonomy file grows past ~30 entries in a single host.
- Two entries share a Levenshtein distance ≤ 2 (`code_review` / `code-review`).
- Revenium "spend by task-type" shows a long-tail histogram instead of a power-law distribution.
- The `unclassified` bucket is small but the second-largest bucket is `misc` or `other` (means the agent is using catch-alls instead of looking up).

**Phase to address:**
Taxonomy invariants phase (the phase that designs `task-taxonomy.json` and the agent prompt). Normalization is a single-line bash regex or Python `re.sub`; the dedupe pass is a separate tool that ships post-MVP. Do NOT defer normalization — fragmenting taxonomies are very hard to merge retroactively because Revenium-side data carries the unmerged labels.

---

### Pitfall 2: "Substantive turn" judgment drifts in both directions

**What goes wrong:**
The skill prompt instructs the agent to classify substantive turns and skip trivial ones. Two failure modes appear:
- **Over-classification:** Agent writes a marker for "User said `thanks` → I responded `you're welcome`" with `task_type: acknowledgment`. Now `acknowledgment` is in the taxonomy; future trivial acks fragment further into `ack`, `acknowledgment`, `confirmation`. Classification turns themselves cost tokens (GUARDRAIL), so taxonomy pollution and guardrail spend grow together.
- **Under-classification:** Agent decides "this turn isn't substantive enough" for real work — a code review, a quick refactor, a planning conversation. Markers are missing for hours of session work. Cron falls back to `--task-type unclassified` and most of the spend ends up in the catch-all bucket — defeating the feature.

**Why it happens:**
"Substantive" is a soft judgment with no shared definition across turns. LLMs anchor on whatever examples are nearby in context. Under load (long sessions, many tool calls, distracting errors), the model defaults to either "always classify" (verbose mode) or "rarely classify" (terse mode).

**How to avoid:**
- **Replace the soft judgment with a hard rule with one fuzzy escape hatch.** Define substantive operationally in `SKILL.md`:
  > "Classify a turn if ANY of: (a) you called a tool other than read-only file inspection; (b) you produced > 200 words of new content; (c) the user asked a question requiring multi-step reasoning. Skip a turn if your entire output is ≤ 2 sentences and called no tools."
- **Include 3-4 canonical examples in the prompt** — one obvious substantive (code review with tool calls), one obvious trivial (single-line clarification), one borderline that should classify (5-paragraph explanation, no tools), one borderline that should not (multi-line greeting). Anthropic's context-engineering guidance specifically advises canonical examples over rule lists (see Sources).
- **Make the default safe.** If the agent is uncertain, the documented contract is "fall back to `unclassified` by not writing a marker." Under-classification is recoverable (the cron still meters the tokens, just labeled `unclassified`); over-classification pollutes the taxonomy permanently. Bias the prompt toward skipping rather than minting.
- **Anti-pollution guard:** The taxonomy file is allowed to grow, but the cron rejects markers whose `task_type` matches a static blocklist (`ack`, `acknowledgment`, `greeting`, `confirmation`, `hello`, `thanks`). These labels never make it onto Revenium-side rows. Document the blocklist in `SKILL.md` so the agent learns not to emit them.

**Warning signs:**
- `unclassified` share of metered tokens > 60% — under-classification.
- A label representing < 0.5% of total token spend but > 5% of marker count — over-classification of low-cost turns (the classic guardrail-only-spend signature).
- Marker count per session > 2× the number of tool calls in that session — agent is classifying read-only or trivial turns.

**Phase to address:**
Prompt design phase (SKILL.md authoring). The hard rule + canonical examples must ship in v1; the blocklist guard ships with the cron split phase. Both are cheap to add; both are very expensive to retrofit once Revenium-side data is polluted.

---

### Pitfall 3: Marker file growth in long sessions starves the cron

**What goes wrong:**
A long Hermes session (days, hundreds of substantive turns) produces a `<session_id>.jsonl` of thousands of lines. The cron has to read every marker file every minute to compute splits. At ~10K markers across all open sessions, the per-tick I/O approaches or exceeds the 60-second cron interval, and ticks start overlapping. Cron then races with itself — the same window is read by two cron processes, both decide to split, and the ledger gets duplicate (session, marker_id) entries.

A real-world reference point: a JSONL transcript file grew to 113 MB / 25,927 lines and pushed its consumer to 100% CPU and unresponsiveness (see Sources). Marker files will be smaller per line than transcript files, but the failure mode is the same.

**Why it happens:**
JSONL is append-only by design. The contract doesn't natively support rotation; the cron has no incentive to truncate; the agent has no view of the file's size from inside its turn. "Just a marker per turn" sounds bounded but isn't.

**How to avoid:**
- **Read only the unprocessed tail.** The ledger already records the last processed offset per session (extend the schema to carry `last_marker_offset` alongside `total_tokens`). On each tick, `seek(last_marker_offset)` and read forward only. This collapses per-tick cost from O(markers_total) to O(new_markers).
- **Rotate per session.** When a session is closed (Hermes's session row in `state.db` has an `ended_at` ≠ null), rename the marker file to `<session_id>.jsonl.closed` and stop scanning it on future ticks. After 14 days, archive `*.closed` files to a tarball or delete.
- **Soft cap per file.** If a single session's marker file exceeds 5 MB (or 5,000 lines), the cron emits a warning to `revenium-metering.log` and the SKILL.md prompt instructs the agent: "If your session has > 500 markers, classify only substantive-with-tools turns; skip prose-only substantive turns." This is a degraded-mode contract, not a hard cap.
- **Cron lockfile.** Take a `flock(2)` on `~/.hermes/state/revenium/.cron.lock` at the top of `cron.sh`. If a previous tick is still running (lock held), this tick exits 0 and logs `cron: skipping, prior tick still active`. Prevents overlapping ticks from racing on the ledger.

**Warning signs:**
- Per-tick wall time in `revenium-metering.log` trending upward.
- Cron logs showing `prior tick still active` (means you've hit the lockfile).
- Disk usage under `~/.hermes/state/revenium/markers/` > 100 MB on a single host.
- A specific session_id appearing repeatedly in the cron log with growing marker counts (long-lived session that may need closing).

**Phase to address:**
Marker file design phase (the phase that defines the marker JSONL schema and writer/reader contract). Tail-reading and the lockfile are MVP; rotation/archival is post-MVP but should be designed-for from day one (the `<session_id>.jsonl.closed` rename convention costs nothing now and prevents a painful migration later).

---

### Pitfall 4: Concurrent writer/reader race on the marker file

**What goes wrong:**
Two specific failure modes:
1. **Torn line on read.** The agent flushes a partial JSON line; the cron reads at exactly that moment and sees `{"ts":1715520000,"task_typ` (incomplete). The cron's JSON parser raises. If the cron has `set -uo pipefail`, the whole tick aborts; if it has `|| true`, the marker is silently skipped.
2. **Lost line via non-atomic append.** On a non-POSIX-strict filesystem (some FUSE mounts, NFS without `lockd`), `O_APPEND` does not guarantee atomic-up-to-PIPE_BUF. Two concurrent appends (extremely unlikely here since only the agent writes, but possible if a future feature has the cron append too) interleave. Per Sources: POSIX O_APPEND guarantees per-write atomicity only up to PIPE_BUF (~4 KB on Linux); larger writes can interleave; non-POSIX systems offer weaker guarantees.

**Why it happens:**
The cron and the agent are independent processes with no shared lock. The marker writer (agent) uses whatever JSON-writing primitive its host language exposes; the marker reader (cron) opens the file at arbitrary moments.

**How to avoid:**
- **Write the line in a single atomic write under PIPE_BUF.** Each marker line should be ≤ 4 KB (trivially true for `{ts, task_type, operation_type, turn_index}` — typical line is 80-150 bytes). Instruct the agent (in `SKILL.md`) to emit the marker as a single `print()` with the trailing newline included, or to use the host file system's append-mode write. This makes the marker write atomic on POSIX.
- **Reader uses "complete-line" parsing.** The cron reads the file, splits on `\n`, and parses only lines that successfully `json.loads()`. A torn last line is silently held over for the next tick (when it will have been completed). Use stdlib Python; do not rely on bash splitting.
- **Lockfile for any path that writes from both sides.** If a future feature has the cron writing to a marker file (e.g., to mark "processed" inline), introduce `fcntl.flock` on the file. The current design (agent writes, cron reads-only) avoids this entirely — keep it that way.
- **Document the boundary.** `CLAUDE.md` and `references/setup.md` should state explicitly: "Marker files are agent-writeable, cron-readable. No other process writes." This is a social contract that maps to the existing "no writes to state.db" discipline.
- **Don't use SQLite WAL** for markers. Tempting (atomic writes, durable reads), but it adds a runtime dependency, breaks the "human-readable flat-file state" property the rest of the skill has, and the problem doesn't justify it.

**Warning signs:**
- Cron log entries showing `JSON parse error at <session_id>.jsonl line N`.
- Marker count parsed by cron consistently one less than agent-side write count (off-by-one suggests the trailing line is torn).
- On NFS or unusual FS: any sustained desync between marker count and Revenium-side row count.

**Phase to address:**
Marker file design phase. The "single-write-under-PIPE_BUF + reader-tolerates-torn-tail" pattern needs to be in the first marker writer/reader implementation. Adding flock later is fine; getting the line-atomicity wrong from day one will cause inexplicable Revenium drift that's hard to diagnose.

---

### Pitfall 5: Equal split (S2) bias undercounts work, overcounts guardrails

**What goes wrong:**
Suppose a cron window has 1 work turn (8,000 tokens spent classifying-and-doing real work) and 1 classification turn (300 tokens, GUARDRAIL). Markers: 1 work + 1 GUARDRAIL. Equal split = each gets 4,150 tokens. Revenium sees:
- `task_type: refactor, operation_type: CHAT, tokens: 4,150` (under-attributed by ~50%)
- `task_type: refactor_classification, operation_type: GUARDRAIL, tokens: 4,150` (over-attributed by ~13×)

GUARDRAIL spend looks enormous; work spend looks small. Operators conclude "classification is too expensive" and disable the feature.

The bias roughly self-cancels at high volume (`PROJECT.md` Key Decisions assertion), but the **direction is not random** — it systematically favors smaller turns. Classification turns are almost always shorter than work turns, so GUARDRAIL share is structurally overstated.

**Why it happens:**
S2 was chosen for simplicity (`PROJECT.md`: "Simplest defensible attribution given no per-turn token data"). The decision is correct for v1, but the bias is not bounded in the worst case — a single huge work turn paired with a single tiny GUARDRAIL turn gives a 50/50 split for what should be ~96/4.

**How to avoid:**
- **Ship the bias warning in the docs.** `references/setup.md` should have a "How attribution works" section that states: "GUARDRAIL share is overstated when work turns are much larger than classification turns. Read GUARDRAIL share as an upper bound."
- **Synthetic-floor check in tests.** Add a test that constructs a fixture window with 1 large turn + 1 small turn and asserts the cron's S2 output ratio matches the equal-split — i.e., pins the known bias rather than hiding it. The test is a contract: "we know this is wrong, here's how wrong."
- **Telemetry to detect when bias matters.** Have the cron emit (to `revenium-metering.log`) a per-tick line: `S2: window=<n_markers>, mean_per_marker=<delta/n>`. When `n_markers == 2` and one is GUARDRAIL, log a `S2: classification-dominated window, attribution may be lossy`. This gives operators a debug signal without firing alerts.
- **Defer S3/S4** as `PROJECT.md` already does, but keep them on the roadmap with a clear trigger: "if Revenium analytics consistently show GUARDRAIL ≥ 20% of spend on a host where users report it should be < 5%, escalate to S3."
- **Make S2 a configurable strategy.** The cron's split function should take a `--split-strategy=equal` flag; future strategies plug in without re-architecting. Cheap insurance.

**Warning signs:**
- Revenium "GUARDRAIL share of spend" > 15% on any host.
- Per-host GUARDRAIL share that varies wildly between hosts running similar workloads (means S2 bias is interacting with usage patterns).
- A pair of (work, GUARDRAIL) markers in the same cron window where they get equal token attribution but the user reports the work turn was much longer.
- Cumulative `unclassified` tokens trending down while GUARDRAIL trends up — markers are appearing but the work-vs-guardrail balance is wrong.

**Phase to address:**
Cron split phase (the phase implementing the S2 splitter in `hermes-report.sh`). Make the strategy pluggable and document the bias in `references/setup.md` at the same time the splitter ships. Bias becomes a noticeable problem when classification-turn share exceeds ~30% of marker count, which happens earlier than expected if Pitfall 2 (over-classification of trivial turns) is not also addressed.

---

### Pitfall 6: Agent forgets to write the marker

**What goes wrong:**
The agent reads `SKILL.md`, processes the user request, performs real work (writes 50 lines of code, runs tests, commits), and never writes the marker. Tokens spent are real; on the next cron tick, the session has no markers in the window, and the cron defaults to `--task-type unclassified`. After many sessions, `unclassified` dominates Revenium-side analytics — the feature is technically working but providing no signal.

`PROJECT.md` already notes the documented fallback: "Sessions with no markers in the current window… emit a single metering call with `--task-type unclassified`." But the fallback is the failure mode, not the feature.

**Why it happens:**
1. **Context dilution at long sessions.** Hermes loads `SKILL.md` on every turn, but in a 50-turn conversation, the SKILL.md preamble competes with the user's most recent request, tool outputs, and error tracebacks. Per Sources, instruction adherence degrades observably past ~3,000 tokens of context — well below most modern context windows but easy to hit in a long agentic session.
2. **Marker writing is a "boring" terminal step.** After completing the user's task, the agent's attention is on the user's reply; writing a marker is a chore the model may skip if not strongly anchored.
3. **No enforcement loop.** Unlike the budget-halt check (which has a strong "ABSOLUTE FIRST — NON-NEGOTIABLE" framing), the marker write is incidental. Strong-framing one thing per session is fine; strong-framing two things competes for attention.

**How to avoid:**
- **Move the marker write into the SKILL.md's existing closing-discipline pattern.** The halt-check is the opening discipline. Add a "FINAL ACTION — MARKER WRITE" section at the end of SKILL.md that runs after the work is complete: "Before responding to the user, if the turn was substantive (Pitfall 2 definition), append a marker to `~/.hermes/state/revenium/markers/<session_id>.jsonl`."
- **Pin one canonical example** showing the exact bash one-liner or Python snippet the agent should emit. LLMs follow examples more reliably than prose instructions.
- **Make the cost of forgetting visible.** Have the cron, when emitting `--task-type unclassified`, log `unclassified: <session_id> ($<estimated_cost>) — agent did not classify`. Operators can grep this in `revenium-metering.log` to see where the feature is failing.
- **Don't try to enforce inline.** Resist the temptation to add "if you did not write a marker, do X" — this branches the prompt and adds context. Accept that the agent will sometimes skip; rely on the fallback + telemetry to recover.
- **Periodic "did you classify your last N turns?" check.** A weak nudge in SKILL.md: "If you have completed multiple substantive turns this session without writing a marker, write one now covering the most recent." This is best-effort, not enforcement.
- **Halt-check pattern is sacred.** Do not modify or weaken the halt-check framing in SKILL.md to make room for marker discipline — the budget-halt is load-bearing safety; marker writes are an analytics nicety. Different sections, different priority.

**Warning signs:**
- `unclassified` share of total tokens > 40% after the feature is deployed for a week.
- Sessions with substantial token usage and zero markers (cron can log this — "session <sid>: 50K tokens this window, 0 markers").
- A spike in `unclassified` correlating with very long sessions (suggests context-dilution dropout).

**Phase to address:**
Prompt design phase. The FINAL ACTION pattern, canonical example, and operator-visible telemetry all ship in the first SKILL.md update. The "weak nudge" is optional and only ships if real-world dropout rate is high.

---

### Pitfall 7: SKILL.md instructions get deprioritized against competing context

**What goes wrong:**
The SKILL.md is reloaded on every turn but it competes with the user's prompt, prior turns, tool outputs, error tracebacks, and other skill prompts. Long context (per Sources, degradation starts around 3,000 tokens) causes the model to follow the most recent or most salient instructions and drop the SKILL.md preamble's instructions. Specifically:
- The halt-check (already load-bearing) survives because it's framed as "ABSOLUTE FIRST — NON-NEGOTIABLE" and is a single sentence.
- The new classification instructions are longer and less viscerally framed. They lose first.

**Why it happens:**
LLMs do not give equal weight to all instructions in context. Recency bias, salience bias, and "natural reading order" mean a long markdown body gets compressed in attention. The SKILL.md as currently written is already at the edge of what reliably stays prioritized; adding several paragraphs about taxonomy lookup, marker writing, and substantive-turn judgment risks pushing the halt-check itself out of priority.

**How to avoid:**
- **Keep classification instructions short and end-loaded.** Put taxonomy/marker instructions in the last section of SKILL.md, after the budget-halt block. Position-wise, the most recent instruction wins; end-loading the new content gives it recency-bias help.
- **Move details to references/, not the main SKILL.md.** SKILL.md says "see `references/task-classification.md` for the full taxonomy lookup procedure." Hermes loads SKILL.md eagerly; references/ is loaded on demand. This keeps the main prompt small.
- **One canonical example beats three rules.** Per Anthropic's context-engineering guidance (Sources): "curate a set of diverse, canonical examples" instead of stuffing edge cases. One full example of {read taxonomy → match → write marker → continue} is worth more than three abstract rules.
- **Do not weaken the halt-check.** The halt-check's "ABSOLUTE FIRST — NON-NEGOTIABLE" framing is the priority anchor. Do not add competing "ABSOLUTE" framings — that dilutes the original. Use weaker language ("After your response, append a marker if substantive") for non-safety instructions.
- **Test the prompt invariants.** Extend `test_skill_frontmatter_has_hermes_metadata` to assert (substring) the halt block still appears, the halt block precedes the classification block, and the classification block is < N lines. Pinning structure is cheap.

**Warning signs:**
- Halt-check failure rate ticks up after classification instructions ship (regression — the new content displaced the old).
- Markers appearing only on short conversations; long conversations have no markers (instruction dropout under context pressure).
- The agent writes a correctly-formed marker but to the wrong path (it half-remembered the instruction).

**Phase to address:**
Prompt design phase, BEFORE the marker writer phase ships. Verify the existing halt-check still fires reliably in long sessions after the new instructions are added, ideally with manual end-to-end tests against representative session lengths.

---

### Pitfall 8: Ledger idempotency breaks under partial multi-call failure

**What goes wrong:**
The cron has 5 markers in a window: `[refactor, refactor, code_review, GUARDRAIL_classify, code_review]`. Token delta is 10K, split equally = 2K each. The cron calls `revenium meter completion` 5 times. Calls 1, 2, 4, 5 succeed; call 3 fails (network blip, CLI hiccup). The current ledger format `HERMES:<sid>:<total_tokens>:<ts>` does not record which markers were emitted. On the next tick, the cron sees no new total_tokens delta — it skips the session entirely. Calls 1, 2, 4, 5 are now in Revenium; call 3 is lost forever. The session is under-reported by 2K tokens.

Alternative failure: the cron writes the ledger line *before* the calls and one fails — the cron has recorded "this session has been emitted" but actually one row is missing. Same loss, different ordering.

Alternative failure: the cron writes the ledger line *after* the calls and a transient failure causes the cron itself to abort between call 5 and the ledger write — calls 1-5 succeeded but the ledger isn't updated. On the next tick, the cron re-emits all 5. Double-reporting.

**Why it happens:**
The existing ledger captures a single fact (total_tokens at time T) and assumes a single `revenium meter completion` call per ledger line. The marker-split phase changes that to N calls per ledger line, but the ledger format hasn't caught up.

**How to avoid:**
- **Per-marker ledger lines, not per-session.** Extend the ledger to record `HERMES:v2:<sid>:<total_tokens>:<marker_id>:<ts>`. Each successful meter call appends one line. On retry, the cron skips (session, marker_id) tuples it has already recorded. This preserves idempotency under partial failure.
- **Define a stable marker_id.** The natural candidate: `<turn_index>` (the agent writes it) or `<sha256_short_of_marker_line>` (cron derives it). Either works; pick one and pin it in tests.
- **Construct deterministic transaction-id including marker.** The existing pattern is `transaction-id=${session_id}-${total_tokens}`. Extend to `${session_id}-${total_tokens}-${marker_id}` so even if the ledger is lost, Revenium-side dedupes by transaction-id.
- **Version the ledger.** The existing format is unversioned (already flagged as tech debt in `codebase/CONCERNS.md`). Use the v2 bump as the moment to prefix lines with a version marker; old lines without the marker are treated as legacy (still readable, but skip-only — no new appends to old format).
- **Write the ledger line per-call, not per-batch.** Each successful meter call writes its ledger line before the next call starts. A crash between calls leaves the ledger consistent with what actually shipped.

**Warning signs:**
- Revenium-side row count for a session < marker count for that session (lost calls).
- Revenium-side row count for a session > marker count for that session (double-reported).
- The cron's `revenium-metering.log` shows `warn "Failed: …"` entries that are never followed by a successful retry on the next tick.
- Aggregate Revenium-reported tokens diverge from sum of `state.db` totals by > 1% — strongest cross-check, but slow to surface.

**Phase to address:**
Marker-aware idempotency phase (`PROJECT.md` already names it). Ledger versioning + per-marker lines + per-call writes all need to ship together; piecemeal adoption breaks the invariant.

---

### Pitfall 9: Backward-compatibility regression — totals change for existing users

**What goes wrong:**
Before this project: a session emits one `revenium meter completion` per cron window, with no `--task-type` (or implicit default). Revenium aggregates by session.
After this project: a session emits N calls (one per marker). If, for any reason, the sum of those N call's tokens != the single old call's tokens, **the user sees their bill change for the same workload**. Worse: if `--operation-type` was implicitly defaulted to something on the Revenium side and is now explicitly `CHAT`, the cost calculation may change (different op types may have different cost models).

The user reports "Revenium is now charging more for the same Hermes usage." Even if the wire-level reporting is more accurate, the perception is a regression. Trust erodes.

**Why it happens:**
The cron now does math the old version didn't (split deltas across markers). Floating-point or integer-division loss in the split can lose tokens — `8000 / 3 = 2666` with `+ 2` left over, lost if not handled. Operation-type defaults can change Revenium-side cost calculations. The skill-side change exposes an implicit server-side dependency the team didn't know existed.

**How to avoid:**
- **Conservation test.** For any cron window, `sum(tokens emitted across all marker calls) == old single-call token count`. Add `tests/test_split_conservation.py` that runs the splitter against representative marker counts (1, 2, 5, 10) and asserts the input delta equals the sum of split outputs — for each of input/output/cache_read/cache_write/cost separately. Integer division remainder goes to the last (or largest) bucket; document the convention.
- **No-marker = byte-identical legacy call.** When a session has zero markers in a window, the cron must emit a call whose argv is *exactly* what the legacy code emitted, plus `--task-type unclassified`. No new flags, no new defaults. Pin this with a snapshot test that records the legacy argv and asserts the new argv differs only in the addition of `--task-type unclassified`.
- **Verify operation-type semantics with Revenium first.** Before defaulting `--operation-type CHAT` for non-guardrail calls, confirm with the Revenium platform team: does the absence of `--operation-type` map to `CHAT` server-side today? If yes, the change is a no-op cost-wise. If no, schedule it as a separate, signposted migration with a release note. Use the Revenium MCP `manage_metering` tool surface (available in this environment) to verify the current default before changing the default.
- **Release-note any behavior change visibly.** `README.md` should call out: "Upgrading from v0.x: total Revenium-reported tokens are conserved. Per-row attribution changes from session-level to marker-level. If you have Revenium dashboards filtering on `operation_type IS NULL`, update them — new rows will set `operation_type = CHAT` or `GUARDRAIL`."

**Warning signs:**
- Beta-tester report: "my Revenium bill changed after the upgrade."
- A test fixture's input token count != sum of split outputs by even 1 token.
- Revenium-side aggregate-by-session count of rows changes character (e.g., went from 1 row/session to many) without the user understanding why.

**Phase to address:**
Cron split phase and Revenium-integration phase. The conservation test is MVP. The Revenium platform side-effects need to be verified BEFORE the split phase ships — block on that confirmation if needed.

---

### Pitfall 10: Marker file contents leak sensitive data

**What goes wrong:**
The agent, in the spirit of "be helpful for analytics," includes a `description` or `summary` field in the marker line: `{"ts": ..., "task_type": "code_review", "description": "Reviewing CVE patch for billing service, attacker chain via X token endpoint"}`. The marker file is world-readable under default `~/.hermes/` perms. The description is now logged plaintext on disk. If `~/.hermes/state/revenium/markers/` is included in a backup, support upload, or `tar` for a bug report, the sensitive data goes with it.

Hermes sessions can include API keys (the user paste-ing a key into the chat), internal product names, customer data, source code under review. Marker files are an unprotected mirror of any of that the agent chose to record.

**Why it happens:**
Helpful agents are biased toward including more context. The marker schema is whatever the agent emits; if the SKILL.md says "include task_type and operation_type," the agent will plausibly include `description` too unless told not to. There's no formal schema enforcement on the file.

**How to avoid:**
- **Allow-list the marker schema in SKILL.md.** Explicitly: "A marker line contains EXACTLY these keys: `ts`, `task_type`, `operation_type`, `turn_index`. No other fields. Do not include task descriptions, file paths, user content, or any free-form text." Be specific — LLMs follow allow-lists better than "don't include sensitive data."
- **Enforce server-side.** The cron, when reading markers, ignores any keys other than the allow-list. Unknown keys are logged-once-per-session and discarded. A test pins the allow-list.
- **task_type is the only free-form field, and it's drawn from a controlled vocabulary.** Vocabulary entries are reviewable by the operator. If the agent invents `task_type: refactor_billing_service_for_cve_2025_X`, the operator can see and merge it during a dedupe pass — but that's a one-time visibility, not a continuous leak.
- **Document the marker file's privacy posture in `references/setup.md`.** "Marker files contain task_type labels drawn from a controlled vocabulary. They do not contain user messages, agent responses, or any free-form context. They are safe to share for debugging."
- **chmod 600 the markers directory.** `install-cron.sh` or `common.sh` should `mkdir -m 700` the markers directory and `umask 077` before any writes. Defense in depth in case the agent ever does leak a description.

**Warning signs:**
- A marker line longer than ~300 bytes (the allow-listed schema is small; long lines mean extra fields).
- During a dedupe pass: vocabulary entries that look like sentences rather than labels.
- A bug report submitted by a user that includes their marker file — does it contain anything they should not have shared?

**Phase to address:**
Marker file design phase. The allow-list schema, the cron-side enforcement, and the directory permissions all ship in v1. Retrofitting privacy onto an existing marker format is much harder than starting with the right contract.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip taxonomy normalization, trust the agent | Saves one regex + one test | Taxonomy fragments within days; Revenium-side rows carry inconsistent labels that are very hard to merge | Never. Normalization is one line of code. |
| Skip marker-file rotation/closed-session handling | Faster MVP | Per-tick cron latency grows with session age; eventually starves the cron | Acceptable for v1 if session counts are small (< 5 active long-lived sessions); not acceptable past pilot |
| Use the old ledger format with new multi-call splits | No ledger schema migration | Partial-failure retries lose data or double-count; very hard to debug after the fact | Never. The v2 ledger is the load-bearing invariant of marker-aware idempotency. |
| Have the cron run without a lockfile | No `flock` dependency | Per-tick cost growth eventually causes overlapping ticks → race on the ledger → real data corruption | Acceptable while per-tick latency < 10s. Add `flock` before it becomes a problem; cheap insurance. |
| Soft "should classify" instructions instead of hard rules | Easier to write | Drift in both over- and under-classification directions; large `unclassified` share | Never for production. Soft rules are okay during prototype only. |
| Include `description` or other free-form fields in markers | "Useful context for debugging" | Sensitive data leaks; privacy review on every backup/support upload | Never. Markers are typed analytics, not logs. |
| Single ledger file for all sessions, scanned with grep | Existing pattern | Per-tick `grep` cost grows linearly with history (already flagged in `codebase/CONCERNS.md`) | Existing debt; this project should add tail-reading and rotation, not perpetuate the grep pattern |
| Implicit `--operation-type` (rely on Revenium default) | One fewer flag | Server-side default changes break attribution silently; cost-model surprises | Acceptable only after explicit confirmation from Revenium platform team that the default is stable |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `revenium meter completion` CLI | Assume current flag set is stable; ship without pinning a min CLI version | Pin minimum CLI version in `README.md`; parse `revenium meter completion --help` at top of `hermes-report.sh` and skip-with-warn if a required flag is missing. (Also called out in `codebase/CONCERNS.md`.) |
| Revenium platform default `operation_type` | Change skill-side default without checking server-side default | Use the Revenium MCP `manage_metering` tool to verify the server-side default before defaulting on the client side; document the contract in `references/setup.md` |
| Hermes `state.db` schema | Treat as stable | Pin expected columns in a test fixture; warn-and-skip if a column is missing rather than crash. The current `IFS='|'` parse is already brittle (flagged in `codebase/CONCERNS.md`) |
| Hermes `SKILL.md` reload behavior | Assume Hermes loads SKILL.md on every turn unconditionally | Verify in Hermes docs; if context-window pressure can drop SKILL.md preambles, design for that (end-load critical instructions; use references/ for details) |
| Marker file consumer order | Assume markers are read in write-order | They are (single-writer, append-only), but the cron should sort by `ts` defensively for robustness against future multi-writer scenarios |
| Cron environment | Assume cron has the same `PATH` as interactive shell | Already handled by `ensure_path` in `common.sh`; don't break it. New scripts must source `common.sh` first. |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-scan every marker file every tick | Per-tick wall time grows linearly with cumulative marker history | Tail-read from `last_marker_offset` recorded in the ledger | When any session has > 1,000 markers OR when active session count > 20 |
| Grep-scan the ledger per session per tick | Already a known issue (`codebase/CONCERNS.md`); compounded as ledger grows with multi-call rows | Per-session reverse-tail (`tac \| grep -m1`); rotate ledger weekly | Ledger > 10 MB on slow disks; ~6 months of moderate use |
| Many `python3 -c` invocations per tick | Python startup ~50-100ms × 8-11 invocations × N sessions | Consolidate into one Python script per session that reads stdin and prints all derived values; already flagged in `codebase/CONCERNS.md` | 10+ active sessions per minute |
| Sync ledger writes (every successful call) | Disk I/O dominates cron wall time | Per-call ledger appends are needed for idempotency under partial failure — accept the I/O cost. Tune by batching only if profiling shows > 5s spent on ledger writes per tick | Never problematic at this project's scale |
| Reading the full taxonomy file on every classification turn | Adds tokens to every agent turn | Cap the taxonomy at ~25 entries (Pitfall 1); move full definitions to `references/task-classification.md`, list only keys in `SKILL.md` | Taxonomy grows past 50 entries → in-prompt cost noticeable |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Free-form `description` fields in markers | Sensitive session content leaks via on-disk plaintext markers | Allow-list the marker schema; cron-side enforcement; document privacy posture |
| World-readable markers/ directory | Local-multiuser data exfiltration | `mkdir -m 700`; `umask 077` for marker writes; verify in `install-cron.sh` |
| Trusting taxonomy file path is under user control | Adversary with write access to `task-taxonomy.json` can plant malicious label values that the cron passes verbatim to `revenium meter completion --task-type` | Validate task_type values against `^[a-z][a-z0-9_]{1,31}$` regex before passing to CLI; reject malformed; log+drop the marker |
| Marker schema accepts arbitrary nested JSON | Adversary writes a 10 MB marker line; cron OOMs trying to parse | Cap line length at 4 KB (matches Pitfall 4 atomic-write boundary); cron rejects oversized lines |
| Pass marker contents into shell strings | Same shell-injection class as the latent bug in `hermes-report.sh:90` flagged in `codebase/CONCERNS.md` | Marker values reach Python via `os.environ` or stdin; never bash-interpolated into `python3 -c "…"` |
| Cron reads marker file with elevated privileges | n/a today (cron runs as user) — but if anyone proposes a system cron for "centralized metering," refuse: trust boundary changes | Keep the cron user-owned; document in `references/setup.md` |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Operator sees a Revenium dashboard with 40 fragmented task-types and concludes "this is broken" | Loss of confidence in the feature on day 2 | Ship a default dedupe-warning tool (`tools/audit-taxonomy.py`) operators can run; recommend running it weekly during early adoption |
| User upgrades and sees their bill change | "The skill is overcharging me" | Conservation test + release note + opt-in: ship the marker split off by default, let users enable via config flag after they see the docs |
| User stares at marker files and asks "what is this for?" | Confusion, manual deletion, broken cron | A `references/marker-files.md` doc that explains the contract in 200 words; also a top-of-file comment in each marker JSONL when first created (or a sibling `README.md` in `markers/`) |
| Halt-check stops firing reliably after the upgrade | Budget enforcement silently weakened — the most dangerous regression in this whole project | Prompt-invariant tests + manual end-to-end check in long-session scenarios before shipping |
| The agent says it's classifying but no marker appears | User trust drops; debugging unclear | Have the cron emit a clear `unclassified: <sid>` log line; have a `bash scripts/show-recent-markers.sh <session_id>` debug command |
| Taxonomy file edits by the user are silently overwritten by the agent | Power user customization lost | The agent is the writer of record. If the user wants to curate, run the dedupe pass — don't hand-edit. Document this explicitly. |

## "Looks Done But Isn't" Checklist

- [ ] **Marker writer**: Often missing single-write-atomic discipline — verify a marker line is < 4 KB and is written with a single `write()` call (POSIX atomicity guarantee).
- [ ] **Taxonomy normalization**: Often missing — verify the cron normalizes `task_type` before passing to `revenium meter completion`, not just the agent's good intent.
- [ ] **Ledger v2 migration**: Often missing legacy-read fallback — verify the cron reads both old (unversioned) and new (`HERMES:v2:…`) lines without crashing.
- [ ] **Per-marker idempotency**: Often missing — verify re-running the cron after a fake partial failure (kill it between meter calls) doesn't double-report any (session, marker_id).
- [ ] **Conservation test**: Often missing — verify sum of split tokens equals input delta, exactly, for every numeric column.
- [ ] **No-marker backward compat**: Often missing — verify a session with no markers emits an argv that differs from legacy only by `--task-type unclassified`.
- [ ] **Halt-check still fires after prompt changes**: Often broken silently — verify the halt-check fires correctly in long-session scenarios after the new classification instructions ship.
- [ ] **Allow-listed marker schema**: Often weakened by "just one more field" — verify the cron rejects/strips any non-allow-listed keys, with a test fixture.
- [ ] **Marker directory permissions**: Often left at default — verify `~/.hermes/state/revenium/markers/` is mode 700.
- [ ] **GUARDRAIL telemetry**: Often missing — verify the cron logs a warning when a window is classification-dominated (so operators can spot Pitfall 5).
- [ ] **Closed-session marker file rotation**: Often deferred — verify there's a strategy (even if just a rename convention) before marker files start accumulating.
- [ ] **Operator tooling**: Often missing — verify there's `audit-taxonomy.py`, `show-recent-markers.sh`, and equivalent debug commands so operators don't have to grep raw files.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Taxonomy fragmented (Pitfall 1) | MEDIUM | Run `tools/dedupe-taxonomy.py` to propose merges; manually approve; rewrite historical markers to use canonical labels; emit a "label remap" notice to Revenium support so dashboards can be retroactively merged. Cost grows with how long fragmentation went undetected. |
| `unclassified` dominates (Pitfall 2 or 6) | LOW | Strengthen SKILL.md examples; ship a stricter version. Historical `unclassified` data stays unclassified — accept the lost period. |
| Marker file grew unbounded (Pitfall 3) | LOW-MEDIUM | Manual rotation: `mv <sid>.jsonl <sid>.jsonl.closed` for ended sessions; truncate `.closed` files older than N days; ship the proper rotation logic. |
| Torn lines / corrupt markers (Pitfall 4) | LOW | Cron's "skip unparseable, hold over partial last line" handles this transparently. If it's persistent, audit the marker writer for non-atomic writes. |
| GUARDRAIL share grossly overstated (Pitfall 5) | MEDIUM | Either ship S3 (token-weighted split, needs marker-side token-count hint), or document the bias and live with it. Revenium dashboards can be re-aggregated with a "GUARDRAIL × 0.1" weighting hack as a workaround. |
| Halt-check stopped firing (Pitfall 7) | HIGH — this is a safety regression | Revert the SKILL.md change immediately; re-add classification instructions in a less invasive form (move to `references/`, shorten the body, end-load). |
| Double-reported or lost rows (Pitfall 8) | HIGH | Need Revenium-side support to identify and refund/correct double-reports; lost rows are accepted as data loss. Prevention via per-marker ledger lines is much cheaper. |
| Bill changed for existing users (Pitfall 9) | HIGH | Roll back the version; investigate the conservation-test gap; ship a fix. Reputation damage may exceed the technical cost. |
| Sensitive data in marker files (Pitfall 10) | MEDIUM-HIGH | Audit marker files for non-allow-listed keys; sanitize on the host; tighten SKILL.md instructions; review what's been shared in support tickets/backups for that period. |

## Pitfall-to-Phase Mapping

The project has roughly four design phases (per `PROJECT.md` Active section): taxonomy invariants, marker file contract, cron split, and ledger idempotency. Plus a cross-cutting prompt design phase that touches all of them.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Taxonomy fragmentation | Taxonomy invariants + Cron split (normalization in both writer and reader paths) | `tests/test_taxonomy_invariants.py` regex check; periodic manual taxonomy audit |
| 2. Substantive-turn judgment drift | Prompt design (SKILL.md) | Manual review of `unclassified` share after one week of pilot; cron-side blocklist test |
| 3. Marker file growth | Marker file contract + Cron split | Test that exercises a fixture marker file of 5,000 lines and asserts per-tick wall time < 5s; lockfile test |
| 4. Concurrent reader/writer race | Marker file contract | Test that writes a marker mid-read and asserts the partial line is held over, not crashed-on |
| 5. Equal-split bias | Cron split | Conservation test + synthetic-bias test that pins the known bias direction |
| 6. Agent forgets to classify | Prompt design (SKILL.md) | Cron-side telemetry log line for sessions with tokens but no markers; manual review during pilot |
| 7. SKILL.md instructions deprioritized | Prompt design (SKILL.md), enforced before marker file contract ships | Extended `test_skill_frontmatter_has_hermes_metadata` asserting halt block presence + position |
| 8. Idempotency under partial failure | Ledger idempotency (marker-aware) | Test that simulates a partial failure (kill cron mid-batch) and asserts retry doesn't double-report |
| 9. Backward-compat regression | Cron split + Revenium integration verification | Snapshot test of legacy-mode (no markers) argv; conservation test on splits |
| 10. Privacy leakage in markers | Marker file contract | Allow-list test; marker-line length test; directory permission test |

---

## Sources

**Domain (LLM agent classification, prompt engineering, context degradation):**
- [Effective context engineering for AI agents (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — canonical-example guidance over rule lists; informs Pitfalls 2, 6, 7
- [Context Degradation in LLMs (Emergent Mind)](https://www.emergentmind.com/topics/context-degradation-in-large-language-models) — instruction-adherence degradation starting around 3,000 tokens of context; informs Pitfalls 6, 7
- [Prompt Length vs. Context Window: The Real Limits Behind LLM Performance](https://dev.to/superorange0707/prompt-length-vs-context-window-the-real-limits-behind-llm-performance-3h20) — long-context reasoning degradation evidence
- [LLM Agents | Prompt Engineering Guide](https://www.promptingguide.ai/research/llm-agents) — agent profiling and persona-style instruction patterns

**Controlled-vocabulary deduplication, normalization, fuzzy matching:**
- [Fuzzy Matching 101: The Complete Guide to Accurate Data Matching](https://dataladder.com/fuzzy-matching-101/) — normalization-then-fuzzy-match workflow; informs Pitfall 1
- [Text Normalization: Unicode Forms, Case Folding & Whitespace Handling for NLP](https://mbrenndoerfer.com/writing/text-normalization-unicode-nlp) — normalization fundamentals for label deduplication
- [Deep Dive into String Similarity: Edit Distance to Fuzzy Matching](https://medium.com/data-science-collective/deep-dive-into-string-similarity-from-edit-distance-to-fuzzy-matching-theory-and-practice-in-68e214c0cb1d) — Levenshtein and stem-matching tradeoffs

**POSIX O_APPEND atomicity / concurrent JSONL access:**
- [Appending to a File from Multiple Processes (Chris Wellons)](https://nullprogram.com/blog/2016/08/03/) — POSIX O_APPEND atomic-per-write-up-to-PIPE_BUF guarantee; informs Pitfall 4
- [JSON Lines (jsonlines.org)](https://jsonlines.org/) — JSONL format properties and tooling
- [Reader Writer Problem: Process Synchronization](https://dev.to/harshm03/reader-writer-problem-process-synchronization-gb) — concurrency fundamentals

**Idempotent retries and partial batch failure (informs Pitfall 8):**
- [Designing robust and predictable APIs with idempotency (Stripe)](https://stripe.com/blog/idempotency) — idempotency-key + per-call commit pattern
- [Making retries safe with idempotent APIs (AWS Builders Library)](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/) — per-call commit boundaries
- [Idempotency in APIs - Why Your Retry Logic Can Break Everything](https://dev.to/fazal_mansuri_/idempotency-in-apis-why-your-retry-logic-can-break-everything-and-how-to-fix-it-345k) — partial-failure recovery patterns
- [API idempotency (Adyen Docs)](https://docs.adyen.com/development-resources/api-idempotency/) — billing-specific idempotency rules

**JSONL log growth / rotation (informs Pitfall 3):**
- [Docker Log Rotation Configuration Guide (SigNoz)](https://signoz.io/blog/docker-log-rotation/) — size-based rotation patterns for append-only JSON logs
- [JSONL for Log Processing — Structured Logging & Analysis (jsonl.help)](https://jsonl.help/use-cases/log-processing/) — JSONL log-processing patterns

**Internal context (load first):**
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/PROJECT.md` — load-bearing project decisions and out-of-scope boundaries
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/codebase/CONCERNS.md` — existing tech debt that this project must not perpetuate (ledger format, provider inference, shell-injection latent bugs)
- `/Users/johndemic/Development/projects/revenium/hermes-revenium/.planning/codebase/TESTING.md` — what's enforceable today (repo-shape tests) and how to add behavior tests

---
*Pitfalls research for: agent-driven task classification with controlled vocabulary, layered on cron + skill-prompt metering pipeline*
*Researched: 2026-05-12*
