# Pitfalls Research

**Domain:** Adding agentic-job lifecycle tracking (create / attribute / outcome) to an existing cron + skill-prompt token-metering pipeline, where job outcomes are immutable and the cron re-runs every minute
**Researched:** 2026-05-14
**Confidence:** HIGH — `revenium jobs` CLI behavior verified directly (`--help` for `create`/`outcome`, `meter completion --task-id`); immutability (409 on second outcome post) and the async create→404 race confirmed against `docs.revenium.io/instrument-your-agents/agent-outcomes`. v1.0 failure modes (taxonomy collapse, dead-predicate silent drop, bash 3.2 `${VAR@Q}`) are documented live-environment lessons in MILESTONES.md / PROJECT.md, not speculation.

---

## Scope note for the roadmapper

These pitfalls are specific to *adding agentic jobs to this exact system*. Phase numbers below are notional (v1.1 roadmap not yet built); they describe the **kind** of phase that must own each prevention. Suggested phase shape:

- **Phase 1 — Marker schema v3 + agent contract** (SKILL.md job block, marker keys, backward-compatible reader extension)
- **Phase 2 — Job ledger + idempotency** (separate job-state ledger, create-once / outcome-once gating)
- **Phase 3 — Cron job pipeline** (`jobs create` → `meter completion --task-id` → `jobs outcome` wiring with ordering/race handling)
- **Phase 4 — Outcome correctness + arc termination** (terminal-marker detection, safe defaults, abandoned-arc handling)
- **Phase 5 — Hardening carry-forward** (bash 3.2 compat, flock, retention guard, dead-helper cleanup) — small, can fold into Phase 1 or run last

Several pitfalls are P0 because the cost of getting them wrong is **unrecoverable** (immutable outcomes) rather than merely a bad row.

---

## Critical Pitfalls

### Pitfall 1: Double-reporting a job outcome (immutable, 409, unrecoverable)

**What goes wrong:**
The cron runs every 60s. The first run that sees a terminated arc calls `revenium jobs outcome <id> --result SUCCESS`. The next run sees the same FINAL ACTION marker still on disk, re-derives "this arc is done", and calls `jobs outcome` again. The Revenium platform returns **409 Conflict** (outcomes are immutable — verified: "a 409 Conflict is returned on any second post to the same job"). Best case the cron logs a confusing error every minute forever; worst case a naive `set -e` wrapper or a retry loop treats the 409 as a transient failure and never advances, or — if outcome-derivation is non-deterministic — a *different* outcome gets attempted and the operator sees noise that looks like the first report failed.

**Why it happens:**
v1.0's idempotency is keyed on `(sid, total_tokens, muid)` in the *metering* ledger. That ledger answers "has this token delta been metered?" It does **not** answer "has this job's outcome been reported?" An outcome is a once-per-`agenticJobId` event with no token delta attached — it is invisible to the existing ledger. Developers reuse the metering ledger by reflex and assume it covers the new call.

**How to avoid:**
- Introduce a **separate job-state ledger** (e.g. `~/.hermes/state/revenium/revenium-jobs.ledger`, path declared in `common.sh`). Append-only, one line per job lifecycle event: `JOB:<agenticJobId>:created:<ts>` and `JOB:<agenticJobId>:outcome:<result>:<ts>`.
- Before `jobs create`: `grep -q "^JOB:${jid}:created:"` → skip if present.
- Before `jobs outcome`: `grep -q "^JOB:${jid}:outcome:"` → skip if present. **Write the ledger line only on exit 0.**
- Treat a 409 from `jobs outcome` as a **terminal success-equivalent** (the outcome already exists server-side) — append the ledger line so it never retries. Do **not** treat 409 as failure. This is the belt to the ledger's suspenders: even if the ledger line was lost, 409 stops the loop.
- Make outcome derivation **deterministic** — the result must come verbatim from the marker, never recomputed, so a retry (if it ever happens) posts the identical value.

**Warning signs:**
- 409 errors in `revenium-metering.log` recurring every minute for the same `agenticJobId`.
- A `jobs.ledger` line for `outcome` that never appears even though `jobs outcome` was invoked.
- Re-running `cron.sh` by hand produces a second outcome attempt.

**Phase to address:** Phase 2 (job ledger + idempotency) — this is the load-bearing invariant; design the ledger before any `jobs outcome` call exists.

---

### Pitfall 2: Double-creating a job across cron re-runs

**What goes wrong:**
Same per-minute re-run problem applied to `jobs create`. Every tick that sees the job's markers re-issues `revenium jobs create --agentic-job-id <id>`. Depending on platform semantics this either errors (duplicate id) or silently upserts/overwrites the job's `--name`/`--type`/`--environment` — and if the agent-minted name drifts between ticks (it won't here, names come from a static marker, but a future writer change could), the job metadata churns.

**Why it happens:**
`jobs create` is less scary than `jobs outcome` (not flagged "immutable" in the CLI help), so it gets less idempotency attention. But "create" on a per-minute loop is still a repeated mutation.

**How to avoid:**
- Same `revenium-jobs.ledger` from Pitfall 1: `grep -q "^JOB:${jid}:created:"` gate before the call; append `JOB:<jid>:created:<ts>` only on exit 0.
- Tolerate an "already exists" error from `jobs create` as success (append the ledger line) — analogous to the 409 belt for outcomes.
- Do **not** depend on `jobs create` being naturally idempotent on the server; the CLI help does not promise it. Treat the local ledger as the source of truth for "have we created this".

**Warning signs:**
- `jobs create` invoked N times for one `agenticJobId` in the log.
- Job `--name`/`--type` in the Revenium UI differs from what the marker declared (overwrite churn).

**Phase to address:** Phase 2 (job ledger), wired in Phase 3 (cron job pipeline).

---

### Pitfall 3: `meter completion --task-id X` lands before `jobs create X` (ordering race)

**What goes wrong:**
Within a single cron tick the natural code order is: create the job, then emit the per-marker `meter completion` calls. But the marker reader in `hermes-report.sh` is structured per-session, and a job's transactions can span multiple sessions / multiple ticks. A `meter completion --task-id <jid>` can fire on a tick *before* the tick that runs `jobs create <jid>` — e.g. the create marker hasn't settled yet, or the create call failed this tick but metering succeeded, or two sessions of the same arc are processed in an order where metering precedes create. Per the Revenium docs, metering ingestion *also* creates the job record asynchronously, and "the outcome lookup may run before the job exists" → a `jobs outcome` posted too soon "can briefly return 404". The same async window means a `--task-id` referencing a not-yet-created job is accepted but the correlation may resolve late, and a too-early `jobs outcome` 404s.

**Why it happens:**
v1.0's cron is `set -uo pipefail` *without* `-e` — it deliberately tolerates per-step failures and continues. That posture is correct for metering (skip a session, retry next tick) but it means a *failed* `jobs create` does **not** stop the subsequent `meter completion`/`jobs outcome` calls. Combined with cron's per-minute cadence, ordering is not guaranteed across ticks.

**How to avoid:**
- **Order within a tick:** always attempt `jobs create` (or confirm it from the ledger) *before* any `meter completion --task-id` for that job, and before `jobs outcome`. Make create-confirmation a precondition gate.
- **Gate `jobs outcome` on local create-confirmation, not just marker presence.** Only call `jobs outcome <jid>` on a tick where `JOB:<jid>:created:` is already in the jobs ledger (i.e. create succeeded on this or an earlier tick). If create hasn't landed, defer the outcome to a later tick — never post an outcome for a job this skill has not confirmed created. This sidesteps the documented 404 race entirely.
- **Do not block metering on create.** `meter completion --task-id` is safe to send even if the job record is still materializing server-side (metering ingestion creates it async). Only the *outcome* is order-sensitive. So: metering can proceed independently; outcome waits for confirmed create.
- **Do not add a hand-rolled retry/sleep loop** around the CLI for the create race. The docs explicitly warn against a second retry layer. The cron's natural 60s re-cadence *is* the retry — a deferred outcome simply lands next tick. This fits `set -uo pipefail` perfectly: a failed step is logged and retried next minute.
- Capture `jobs create` / `jobs outcome` exit codes explicitly with the v1.0 pattern (`cmd_output=$("${cmd[@]}" 2>&1) && cmd_exit=0 || cmd_exit=$?`); branch on the code; never let an error silently fall through as if it succeeded.

**Warning signs:**
- `jobs outcome` 404s in the log.
- Revenium transactions with a `--task-id` that has no corresponding job in `jobs list`.
- An outcome reported for a job whose `created` ledger line is absent.

**Phase to address:** Phase 3 (cron job pipeline) — the create→meter→outcome ordering gate. Outcome-deferral logic touches Phase 4.

---

### Pitfall 4: Ledger / API divergence on partial failure (the asymmetric-write trap)

**What goes wrong:**
Two failure modes, mirror images:
1. **API succeeded, ledger write didn't.** `jobs outcome` returns 0, then the process is killed (session crash, host reboot, `set -uo pipefail` masking, disk full on `>> ledger`) before the `JOB:<jid>:outcome:` line is appended. Next tick the ledger says "no outcome yet" → re-posts → **409**, and if 409 is mishandled, an infinite loop.
2. **Ledger written, API didn't.** A "write ledger first, then call" ordering means a crash between the two leaves a phantom `outcome` line. Next tick skips the call → the outcome **never reaches Revenium** and is silently lost forever (no retry, immutable, no fix).

**Why it happens:**
Any two-step "do side-effecting thing + record that we did it" is non-atomic. v1.0's metering ledger survives this because metering is *idempotent by transaction-id* — a re-send is harmless. Job-create is roughly idempotent (Pitfall 2 belt). But **`jobs outcome` is not idempotent and not replayable** — it is the one call in the system where both divergence directions are genuinely dangerous.

**How to avoid:**
- **Strict ordering: call the API first, append the ledger line only on exit 0.** This makes mode 2 (lost outcome) impossible — a phantom ledger line can never exist.
- For mode 1 (lost ledger line after success): the **409-is-success** rule (Pitfall 1) is the recovery. A re-post after a lost ledger line returns 409; treat 409 as "already done", append the ledger line now, stop. The outcome is correct, just reported once — exactly the desired end state.
- Make the ledger append the **last** statement in the success branch, immediately after the exit-0 check, with no intervening work that can fail.
- Consider `fsync`/atomic append semantics are not worth it here — a single `echo >> file` is one write; the real safety net is 409-as-success, not write durability.
- **Never** wrap the job calls in `set -e` such that a 409 aborts the script — the 409 branch must run to completion to record the ledger line.

**Warning signs:**
- Repeated `jobs outcome` attempts for one job (lost-ledger-line symptom).
- A job in Revenium with metered transactions but no outcome, long after its arc clearly ended (lost-outcome symptom — phantom ledger line).
- Ledger lines whose `outcome` event has no matching successful log entry.

**Phase to address:** Phase 2 (ledger write ordering) + Phase 3 (409/exit-code handling in the cron pipeline).

---

### Pitfall 5: `agenticJobId` taxonomy collapse / fragmentation (the v1.0 lesson, repeated)

**What goes wrong:**
The agent mints `agenticJobId` from an LLM business label + entropy suffix. Two symmetric failures:
- **Collapse:** the LLM picks a bland, generic label for every arc (`task-001`, `agentic-job`, `work`). v1.0 lived this exactly — the task-type classifier collapsed 12 of 16 markers onto `generation` until the prompt was rewritten. With job IDs the entropy suffix means IDs stay *unique*, but the human-readable label becomes useless: every job in the Revenium UI reads `work-a3f9`, `work-c812`, `work-0d41`. Analytics by job *type* are worthless.
- **Fragmentation:** the LLM over-classifies — the same logical arc gets a different label/ID on different turns, or the agent mints a new ID mid-arc. Jobs splinter; one unit of business work shows as five jobs.

**Why it happens:**
This is a *proven* failure mode in this codebase (PROJECT.md Evolution Notes, quick task 260514-nfb). LLM label-minting without explicit anti-collapse prompt framing biases toward the blandest token that fits. Job IDs add a second axis: the entropy suffix masks collapse (IDs look fine) so collapse is *harder to detect* than in v1.0's task-types.

**How to avoid:**
- Reuse the **fix that already worked**: bias the SKILL.md job block toward minting *specific, business-meaningful* labels (mirror `_build_classification_prompt`'s mint-first framing), with 3–4 concrete good/bad examples in the prompt (`refactor-auth-module` good; `task` / `work` / `job` bad).
- Validate the label cron-side: a **forbidden-label blocklist** for the job-name component, exactly as v1.0 enforces `FORBIDDEN = {'ack','greeting',...}` in `hermes-report.sh`'s reader as defense-in-depth. Reject `job`, `task`, `work`, `agentic`, `unknown`, `default` as job-name stems.
- **Arc boundary discipline:** the agent declares the job *once, at arc end*, in the FINAL ACTION marker (PROJECT.md decision D — mirrors v1.0 classify-at-end). Declaring once per arc structurally prevents mid-arc re-minting. The SKILL.md instruction must make "one arc = one job, declared at the end" unambiguous.
- **Detection despite the entropy mask:** add a test/operator check that strips entropy suffixes and counts distinct *stems*. If 80%+ of jobs share one stem, that is collapse — flag it. v1.0 could see collapse directly in the labels; v1.1 must explicitly strip-and-count to see it.

**Warning signs:**
- `revenium jobs list` shows IDs that all share one stem (`work-*`, `job-*`).
- Distinct-stem ratio low across a sample of jobs.
- One Hermes arc producing multiple `agenticJobId`s in the markers.

**Phase to address:** Phase 1 (SKILL.md job block prompt framing + marker contract) — this is where the v1.0 lesson must be baked in. Blocklist enforcement in Phase 3.

---

### Pitfall 6: Arc-boundary mis-identification → attribution leakage across jobs

**What goes wrong:**
Tokens get attributed to the wrong job. If the agent draws an arc boundary in the wrong place, a `meter completion` carrying `--task-id <jobA>` actually belongs to the work of `jobB`. Too-coarse boundaries (one giant arc per session) make jobs uselessly broad — back to per-session granularity, defeating the milestone. Too-fine boundaries fragment (Pitfall 5). And because v1.0's S2 split divides a *session* delta equally across that window's markers, a marker that the agent tagged with the wrong job's `task-id` silently moves real spend onto the wrong job.

**Why it happens:**
An "arc" is a fuzzy, agent-judged concept with no hard signal in `state.db`. The agent has to decide "these 8 turns were one goal-directed unit." Unlike a session (which has a real `sid`), an arc boundary is purely a prompt-induced judgment call. The cron cannot validate it — the cron only sees whatever `task-id` the marker carries.

**How to avoid:**
- Make the SKILL.md arc definition **concrete and operational**, not abstract: tie an arc to a recognizable unit the agent already reasons about (e.g. "one user request and the work to satisfy it", or "one GSD phase/task"). Avoid the word "arc" alone — give a checklist.
- **Default coarse, not fine.** If the agent is unsure, one job per session is the safe failure — it is merely *uninformative*, not *wrong*. Fragmentation and mis-attribution are *wrong*. The prompt should bias toward fewer, well-bounded jobs.
- The `agenticJobId` is minted **once at arc end** in the FINAL ACTION marker; every `meter completion` for that arc gets that one id. Do not let the agent retroactively re-tag earlier turns with a different job — the marker file is append-only and the cron attributes by marker.
- Accept that perfect attribution is impossible (same constraint as v1.0's S2 approximation — PROJECT.md "Out of Scope: per-turn token exactness"). Document the bound: attribution is arc-granular and approximate; do not over-engineer.

**Warning signs:**
- Jobs whose token totals look implausible vs. the work described.
- A session's markers carrying two+ different `task-id`s with no clear arc break.
- Operator feedback that Revenium job breakdowns "don't match what the agent did".

**Phase to address:** Phase 1 (SKILL.md arc-definition prompt). Verification in Phase 4 (live UAT against real arcs, mirroring v1.0's Mac Studio diagnostic loop).

---

### Pitfall 7: Abandoned arc — no FINAL ACTION marker ever written → no outcome

**What goes wrong:**
The agent declares the job and reports the outcome in the *same* FINAL ACTION marker at arc end. But arcs don't always reach their end: the Hermes session is killed, the host crashes, the process is OOM-killed, or — critically — the **budget halt fires mid-arc** and the skill emits the verbatim halt string and stops. In every case no FINAL ACTION marker is written. The cron has metered completions tagged `--task-id <jid>` but will *never* see an outcome marker. The job sits open forever with no outcome.

**Why it happens:**
The "declare + outcome in one terminal marker" decision (D, PROJECT.md) is clean and avoids start/end marker-pair discipline — but it assumes arcs terminate gracefully. Crashes, kills, and budget halts are exactly the cases where the terminal marker is *not* written. v1.0's classifier had a fail-open posture for budget halt; v1.1's outcome reporting has no equivalent yet.

**How to avoid:**
- Decide the policy explicitly and write it down: **an abandoned arc gets no outcome** (open job, acceptable) **or** the cron eventually posts a default outcome.
- Recommended: **a staleness-based safety net.** If a job has a `created` ledger line and metered transactions, but no `outcome` ledger line, and no new markers for that `agenticJobId` for N hours (e.g. 24h, env-overridable like `REVENIUM_MARKER_RETENTION_DAYS`), the cron posts `jobs outcome <jid> --result FAILED` (or a dedicated `CANCELLED`) **once**, recorded in the jobs ledger. This guarantees every created job eventually closes.
- **Pick the safe default deliberately.** An abandoned arc is *not* a success — defaulting to `SUCCESS` would inflate ROI metrics with work that may have failed. `FAILED` or `CANCELLED` is the honest default. The milestone should choose `CANCELLED` (arc did not complete) over `FAILED` (arc completed badly) — abandonment is closer to cancellation. Document the choice; it is immutable once posted.
- Because outcomes are immutable, the staleness window must be **generous** — better to leave a job open an extra day than to post `CANCELLED` on an arc that was merely paused and resumes tomorrow. Tune conservatively.
- Budget-halt case specifically: the skill *knows* it is halting. If feasible, have the halt path write a terminal marker with `result: CANCELLED` before emitting the halt string — turning a silent abandonment into an explicit, correct outcome. This is the cleanest fix for the most common abandonment cause.

**Warning signs:**
- Growing count of jobs in `jobs list` with no outcome and no recent transactions.
- Jobs created during sessions that ended in a budget halt, all outcome-less.
- `jobs.ledger` with many `created` lines and few `outcome` lines.

**Phase to address:** Phase 4 (outcome correctness + arc termination) — staleness net and abandoned-arc default. Budget-halt terminal-marker write touches Phase 1 (SKILL.md halt path).

---

### Pitfall 8: Agent self-reports the wrong outcome (immutable, no fix)

**What goes wrong:**
The agent declares `result: SUCCESS` for an arc that actually failed (or vice versa). The cron faithfully posts it. It is now an immutable historical fact on Revenium; every ROI calculation built on it is wrong, permanently. There is no `jobs outcome --amend`.

**Why it happens:**
The agent is the only thing that can judge arc success, and LLM self-assessment is optimistic — agents tend to report success even when a task was partially done or the user was dissatisfied. v1.0 only ever wrote *labels* (cosmetic if wrong); v1.1 writes *outcomes* (load-bearing for ROI, and immutable).

**How to avoid:**
- This is irreducibly a judgment call, but constrain it: the SKILL.md outcome block must give **concrete, conservative criteria** — "report `SUCCESS` only if the user's stated goal was met and confirmed; if uncertain or the arc ended without confirmation, report `CANCELLED`." Bias toward `CANCELLED` under uncertainty, never toward `SUCCESS`.
- Keep `outcome-type` / `outcome-value` (business signal) **optional** — only attach them when the agent has a hard signal (an actual dollar figure, a confirmed conversion). A guessed `outcome-value` is immutable noise. PROJECT.md already scopes these as optional; the prompt must reinforce "omit unless certain".
- Treat the result as **the agent's claim, attributed**: set `--reported-by` to something identifying the agent/skill (e.g. `hermes-revenium-skill`) so Revenium-side analysts know outcomes are agent-self-reported, not human-verified, and can weight them accordingly.
- Accept the residual risk explicitly in PROJECT.md (like the S2 approximation): agent-self-reported outcomes are best-effort and immutable; the mitigation is conservative defaulting, not correctness guarantees.

**Warning signs:**
- Suspiciously high `SUCCESS` rate across all jobs (optimism bias).
- `outcome-value` figures that don't trace to a real signal.
- Operator spot-checks finding `SUCCESS` on arcs that visibly failed.

**Phase to address:** Phase 1 (SKILL.md outcome-reporting criteria + conservative defaulting). Phase 4 verifies against real arcs.

---

### Pitfall 9: Marker schema evolution breaks the v1.0 reader / breaks backward compat

**What goes wrong:**
Adding job fields (`agentic_job_id`, `job_name`, `job_type`, `result`, `outcome_type`, `outcome_value`) to the marker JSONL can break in two directions:
1. **New reader, old markers:** if the cron reader starts *requiring* the new keys (adds them to `REQUIRED_KEYS`), every existing marker file on a live install — and every marker from a v1.0-era session — fails the `all(k in m for k in REQUIRED_KEYS)` check and is silently dropped. Metering stops for those sessions.
2. **Job-less sessions stop metering as v1.0 did:** the milestone requires marker-less / job-less sessions to "meter exactly as v1.0 does." If job handling is bolted into the main path instead of being a clean additive branch, a session with task-type markers but no job marker could fall through a code path that now expects job fields and either errors or skips.

**Why it happens:**
`REQUIRED_KEYS` is a tempting place to add the new fields. And the marker reader in `hermes-report.sh` is already dense (per-line try/except, muid dedup, ts cutoff, blocklist); a new contributor extends the hot path rather than adding an orthogonal branch.

**How to avoid:**
- **New marker fields are strictly optional in the reader.** `REQUIRED_KEYS` stays exactly as v1.0: `('muid','ts','sid','task_type','operation_type')`. Job fields are read with `.get()` and a `None`/absent default — never added to `REQUIRED_KEYS`.
- A marker with no `agentic_job_id` → that completion is metered exactly as v1.0 (no `--task-id`). A session with zero job markers → zero job-pipeline activity, identical wire output to today. The job path must be a pure **additive overlay**: `if marker.get('agentic_job_id'): cmd+=(--task-id "$jid")`.
- **Version the marker schema explicitly** — a `schema` or `v` field, or treat absence of `agentic_job_id` as "v2 marker". Never infer schema by counting keys.
- Add a regression test: a v1.0-shape marker file (no job fields) must produce byte-identical `meter completion` argv to v1.0. This mirrors v1.0's WIRE-04 8-provider regression discipline.
- The zero-marker fallthrough path (`--task-type unclassified --operation-type CHAT`) must be **untouched** — no `--task-id` ever added there.

**Warning signs:**
- A test or live install where v1.0-era markers stop being metered after upgrade.
- `meter completion` argv for a job-less session differs from v1.0.
- `REQUIRED_KEYS` in a diff containing a job field.

**Phase to address:** Phase 1 (marker schema v3, additive reader extension, regression test for v1.0-shape markers).

---

### Pitfall 10: Bash 3.2 portability regression in new scripts/helpers

**What goes wrong:**
v1.0 shipped broken on the Mac Studio host (bash 3.2.57) because `prune-markers.sh` used `${VAR@Q}` — bash 4.4+ syntax. Any new v1.1 script (job-state helpers, a `jobs.ledger` reader, an abandoned-arc sweeper) that uses bash 4+ features — `${VAR@Q}`, `${VAR^^}`/`${VAR,,}` case conversion, associative arrays (`declare -A`), `mapfile`/`readarray`, `&>>` in older forms, negative array indices — will silently work on the dev machine and break on the live host.

**Why it happens:**
macOS ships bash 3.2 (frozen at the last GPLv2 release); the dev environment likely has a Homebrew bash 5.x on PATH, so 4+ syntax appears to work. This *already happened once* in this exact codebase. `clear-halt.sh:17` still has the latent `${VAR@Q}` bug (DEFERRED-CLEAR-HALT-BASH-32) carried into v1.1.

**How to avoid:**
- Treat **bash 3.2 as the floor** for every script. No `${VAR@Q}`, no `declare -A`, no `mapfile`, no `${var^^}`. Use Python heredocs (already the codebase idiom) for anything bash 3.2 can't express — JSON, arrays, transforms all belong in stdlib Python.
- Fix `clear-halt.sh:17` as part of the v1.1 hardening carry-forward (already on the Active list).
- Add a CI/test check: `bash --version` floor, or lint new scripts with `bash -n` under a 3.2 if available, or a regex test in `test_repository.py` that greps new scripts for `@Q`, `declare -A`, `mapfile`, `readarray`.
- Validate on the Mac Studio host (`ssh 172.16.1.175`) before declaring any phase done — the v1.0 lesson is that the dev checkout lies about portability.

**Warning signs:**
- A script that works in the dev shell, errors on Mac Studio.
- `${VAR@Q}`, `declare -A`, `mapfile` in any new `.sh` diff.
- `bash: ...: bad substitution` in `revenium-metering.log` on the live host.

**Phase to address:** Phase 5 (hardening carry-forward — `clear-halt.sh` fix). Discipline applies to *every* phase that adds a script; bake a portability gate into each phase's success criteria.

---

### Pitfall 11: A new "is this arc terminal?" predicate degenerates to always-true / always-false (dead-predicate, the v1.0 lesson)

**What goes wrong:**
v1.0 shipped a "trivial-skip" heuristic (`tool_count == 0 AND len(response) < 200`) that was **always true** because `response=None` was always passed — silently dropping ~94% of sessions. v1.1 introduces new predicates of exactly the same shape: "does this marker terminate a job?", "is this arc abandoned/stale?", "should this tick post the outcome?". If any of those predicates is wired to an input that is always the same value, it degenerates — and the failure is *silent*: jobs never close (predicate always false) or every tick posts an outcome (predicate always true → Pitfall 1's 409 storm).

**Why it happens:**
The v1.0 dead predicate happened because the value feeding it (`response`) was never actually populated by the calling context. The cron has many layers (sqlite → session loop → marker reader → split → job logic); a predicate added deep in the stack can be fed a default/constant from a layer that doesn't know to populate it. The bug is invisible because the cron logs "skipped N" or "reported N" without explaining *why* a session took a branch.

**How to avoid:**
- For every new boolean predicate, **log the inputs and the decision** at `info`/`debug` level — e.g. `info "job-terminal check: jid=X has_final_marker=true age=...". v1.0's silent drop would have been caught instantly if the skip decision logged its inputs.
- Write a test that exercises the predicate with **both** outcomes — a marker that *is* terminal and one that *isn't* — and asserts the branch taken. v1.0's dead predicate had no test that ever fed it a non-`None` response.
- Audit the call chain: trace every input of a new predicate back to where it is *actually* set, not where it is *declared*. If an input is a function parameter, confirm a caller passes a real value.
- After deploying, **read the live cron log on Mac Studio** and confirm the predicate's branch distribution is plausible (not 0% / 100%). This is exactly how v1.0's 94%-drop was caught.

**Warning signs:**
- A branch counter that is always 0 or always equals the session count.
- Jobs that never close, or outcomes posted every tick.
- A predicate whose input is a function parameter with a default that no caller overrides.

**Phase to address:** Phase 3 (cron job pipeline — terminal/abandoned predicates) and Phase 4 (outcome timing). Logging discipline and dual-branch tests are phase success criteria.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reuse the v1.0 metering ledger for job-create/outcome state | One less file, no `common.sh` change | Metering ledger keys on token deltas; job events have none — conflated semantics, double-outcome bugs | **Never** — job state needs its own ledger (Pitfall 1) |
| Treat 409 from `jobs outcome` as a hard failure | Simple error handling | Cron retries forever, 409 storm in logs, or `set -e` aborts the pipeline | **Never** — 409 must be success-equivalent |
| Skip the abandoned-arc safety net (open jobs forever) | No staleness sweeper to build | Jobs accumulate open in Revenium UI; budget-halted arcs never close; ROI denominators wrong | Acceptable for an MVP/first cut **only if** explicitly documented and a follow-up is filed; budget-halt terminal marker should still ship |
| Add job fields to `REQUIRED_KEYS` in the marker reader | "Cleaner" required-field validation | Every v1.0-era marker silently dropped; metering stops on upgrade (Pitfall 9) | **Never** — new fields are `.get()`-optional |
| Hand-rolled retry/sleep loop around `jobs create` for the async race | Feels defensive | Docs explicitly warn against it; fights the cron's natural 60s retry; lengthens cron runtime | **Never** — defer to next tick instead |
| Mint `agenticJobId` without an anti-collapse prompt | Less prompt-engineering effort | v1.0's exact taxonomy-collapse failure; entropy suffix *hides* it | **Never** — the v1.0 lesson is paid for already |
| Bash 4+ syntax in new scripts (dev shell has bash 5) | Convenient | Breaks on Mac Studio bash 3.2, exactly as v1.0 did | **Never** — bash 3.2 is the floor |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `revenium jobs outcome` | Posting twice; treating 409 as failure | Local jobs-ledger gate + 409-as-success belt; call API first, ledger line on exit 0 only |
| `revenium jobs create` | Assuming server-side idempotency; re-creating every tick | Local `JOB:<id>:created:` ledger gate; tolerate "already exists" as success |
| `revenium jobs outcome` after `meter completion` | Posting outcome immediately → 404 (job created async by metering ingestion) | Gate outcome on a *confirmed local* `jobs create`; defer to next cron tick if not confirmed |
| `revenium meter completion --task-id` | Adding `--task-id` to the zero-marker fallthrough path | `--task-id` only when a marker carries `agentic_job_id`; fallthrough path byte-unchanged from v1.0 |
| `revenium jobs create` SDK retry guidance | Wrapping the CLI in a custom retry/backoff loop | None — let the per-minute cron be the retry cadence; no second retry layer |
| `revenium jobs outcome --outcome-value` | Attaching a guessed monetary value | Omit unless the agent has a hard signal; immutable noise otherwise |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `jobs.ledger` grows unbounded, `grep`-ed every tick | Cron runtime creeps up; `grep` over a large file each session | Bound the ledger via the existing prune mechanism (extend `prune-markers.sh` or a sibling); one line per job lifecycle event keeps it small | Thousands of jobs on a long-lived host |
| Abandoned-arc sweeper scans all jobs every tick | Cron tick scans full job history each minute | Run the staleness sweep on a slower cadence (hourly), or only over jobs without an `outcome` ledger line | Hundreds of open jobs |
| Per-job `jobs get`/`jobs list` API call per tick to check existence | Network call per job per minute | Never call the API to check existence — the local `jobs.ledger` is the source of truth | Any host with API latency |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Agent-minted `agenticJobId` / `job_name` flows unsanitized into the `IFS='|'` while-read | A `|`, newline, or control char in the label corrupts pipe-delimited parsing (v1.0's D-34 / WR-01 already hit this for `agent`/`trace_id`) | Apply the same sanitization v1.0 added: replace `|`, `\n`, `\r` in every agent-supplied field before the pipe-delimited row build |
| `agenticJobId` / `outcome` values interpolated into Python heredocs unescaped | Heredoc injection / broken JSON if a label contains quotes | Pass agent values via environment variables into heredocs (the `MARKERS_DIR=... python3 - <<'PY'` pattern), never string-interpolate into the `<<'PY'` body |
| `outcome` metadata JSON built by string concat | Malformed JSON rejected by CLI, or injection | Build `--metadata` JSON with `json.dumps` in a heredoc, never by hand |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Every job named `work-<hash>` (label collapse) | Revenium job analytics are unreadable; can't group by activity | Anti-collapse prompt + cron-side blocklist (Pitfall 5) |
| Jobs left open forever on budget halt | Operator sees a pile of never-closed jobs; ROI metrics skewed | Budget-halt path writes a `CANCELLED` terminal marker; staleness sweeper closes the rest (Pitfall 7) |
| Optimistic `SUCCESS` on every arc | ROI dashboards overstate success; operator loses trust | Conservative outcome criteria in SKILL.md; bias to `CANCELLED` under uncertainty; `--reported-by` flags self-reported origin (Pitfall 8) |
| Job granularity = per session (too coarse) | "Agentic jobs" indistinguishable from the per-session view this milestone is meant to replace | Operational arc definition in SKILL.md; one arc = one user request / one phase (Pitfall 6) |

## "Looks Done But Isn't" Checklist

- [ ] **Job idempotency:** re-running `cron.sh` by hand twice produces exactly **one** `jobs create` and **one** `jobs outcome` per `agenticJobId` — verify against the jobs ledger and `jobs list`.
- [ ] **409 handling:** simulate a second `jobs outcome` post; confirm the cron treats the 409 as success, writes the ledger line, and does **not** loop or abort.
- [ ] **404 race:** confirm `jobs outcome` is never posted on a tick where `jobs create` has not been locally confirmed.
- [ ] **Backward compat:** a session with v1.0-shape markers (no job fields) produces byte-identical `meter completion` argv to v1.0 — regression test, not eyeballing.
- [ ] **Zero-marker path:** the `--task-type unclassified` fallthrough is byte-unchanged; no `--task-id` added.
- [ ] **Abandoned arc:** kill a session mid-arc (no FINAL ACTION marker); confirm the job either stays cleanly open or is closed `CANCELLED` by the staleness net — never `SUCCESS`, never a 409 loop.
- [ ] **Budget-halt arc:** trigger a halt mid-arc; confirm the job gets a `CANCELLED` outcome (or stays open) — not orphaned silently.
- [ ] **Bash 3.2:** every new script runs on Mac Studio (`ssh 172.16.1.175`, bash 3.2.57) — not just the dev shell.
- [ ] **Predicate sanity:** the cron log on the live host shows a plausible branch distribution for every new predicate (not 0% / 100%).
- [ ] **Label collapse check:** strip entropy suffixes from a sample of `agenticJobId`s; distinct-stem ratio is healthy.
- [ ] **`common.sh`:** the new `jobs.ledger` path (and any other new state file) is declared in `common.sh`, nowhere else — `test_runtime_paths_are_hermes_native` still passes.
- [ ] **Pipe-safety:** an `agenticJobId` containing `|` or a newline does not corrupt the cron's `IFS='|'` parsing.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Double-`jobs outcome` (409) | LOW (if 409-as-success is implemented) / HIGH (if not) | With the belt: nothing — 409 is absorbed, ledger line written. Without it: ship the 409-as-success branch, then manually append missing `outcome` ledger lines to stop the loop |
| Wrong outcome posted (immutable) | HIGH — **unrecoverable** | No fix. `jobs outcome` cannot be amended. Only forward mitigation: tighten SKILL.md criteria so future arcs are correct. Operator must mentally discount historical outcomes |
| Lost outcome (phantom ledger line) | HIGH — **unrecoverable** | No fix once the arc's markers are pruned. Prevention is the only option: API-call-first / ledger-line-second ordering makes this impossible — verify the ordering |
| Job double-created | LOW | Tolerate server "already exists" as success; backfill the `created` ledger line; if metadata churned, `revenium jobs update` to correct it |
| Marker schema broke v1.0 reader | MEDIUM | Revert `REQUIRED_KEYS` to v1.0 set; re-run the cron — dropped markers are still on disk (idempotency ledger ensures no double-report on replay) |
| Bash 3.2 break on live host | LOW | Replace the offending construct with a Python heredoc; re-deploy; the cron is stateless per-tick so a fixed script just works next minute |
| Label collapse in production | MEDIUM | Rewrite the SKILL.md job prompt (v1.0 did exactly this in quick task 260514-nfb); past jobs keep bland names but are not wrong; new arcs improve |
| Abandoned jobs piling up | LOW | Run the staleness sweeper; it posts `CANCELLED` once per stale job and records it |

## Pitfall-to-Phase Mapping

| Pitfall | Severity | Prevention Phase | Verification |
|---------|----------|------------------|--------------|
| 1. Double-report immutable outcome | **P0** | Phase 2 (job ledger) | Run cron twice; exactly one outcome per job; 409 absorbed |
| 4. Ledger/API divergence on partial failure | **P0** | Phase 2 (write ordering) + Phase 3 | Crash-injection test between API call and ledger write; outcome correct or 409-absorbed |
| 3. Ordering race (meter/outcome before create) | **P0** | Phase 3 (cron pipeline) | Outcome never posted without confirmed local create; no 404s in log |
| 8. Wrong self-reported outcome | **P0** (unrecoverable) | Phase 1 (SKILL.md criteria) | Live UAT: outcomes match real arc results; `SUCCESS` rate plausible |
| 7. Abandoned arc, no outcome | **P1** | Phase 4 (staleness net) + Phase 1 (halt path) | Kill session mid-arc; job closes `CANCELLED` or stays cleanly open |
| 5. `agenticJobId` taxonomy collapse | **P1** | Phase 1 (prompt) + Phase 3 (blocklist) | Distinct-stem ratio healthy on a job sample |
| 9. Marker schema breaks v1.0 reader / compat | **P1** | Phase 1 (additive reader) | v1.0-shape markers → byte-identical argv (regression test) |
| 2. Double-create job | **P1** | Phase 2 (job ledger) | Exactly one `jobs create` per id across re-runs |
| 6. Arc-boundary mis-identification | **P2** | Phase 1 (SKILL.md arc definition) | Live UAT: job breakdowns match agent activity |
| 11. Dead-predicate / silent drop | **P2** | Phase 3 + Phase 4 (logging + dual-branch tests) | Live cron log branch distribution plausible (not 0/100%) |
| 10. Bash 3.2 portability regression | **P2** | Phase 5 (`clear-halt.sh`) + every phase adding a script | All new scripts run on Mac Studio bash 3.2.57 |

**Severity key:** P0 = data-integrity / unrecoverable (immutable outcomes raise the stakes — getting these wrong cannot be undone); P1 = feature-correctness or backward-compat breakage (recoverable but bad); P2 = quality / reliability regressions with known recovery.

## Sources

- `revenium jobs create --help`, `revenium jobs outcome --help`, `revenium meter completion --help` — CLI verified directly 2026-05-14 (revenium CLI at `/opt/homebrew/bin/revenium`). Confirms: `--agentic-job-id` required for create; `outcome <id> --result SUCCESS|FAILED|CANCELLED` flagged "(immutable)"; `--task-id` on `meter completion` documented as "correlates the completion with an agentic job (use the same value as agenticJobId)".
- https://docs.revenium.io/instrument-your-agents/agent-outcomes — confirms outcome immutability (**409 Conflict on any second post**, "business outcomes are historical facts"), the async create→**404** race ("outcome lookup may run before the job exists"), SDK retry/backoff (10 attempts, 2s→90s) and the explicit warning **not** to add a second retry loop.
- `.planning/PROJECT.md` — v1.1 milestone scope, Key Decisions D (job-per-arc, declare-once-at-arc-end, `agenticJobId` = label + entropy suffix, immutable-outcome invariant), Constraints, Out of Scope, Evolution Notes.
- `.planning/MILESTONES.md` — v1.0 live-environment lessons: 260514-nfb (taxonomy collapse — 12/16 markers on `generation`), 260514-n8e (dead D-07 trivial-skip predicate dropped ~94% of sessions), DEFERRED-CLEAR-HALT-BASH-32 (`${VAR@Q}` bash 4.4+ break on Mac Studio bash 3.2.57).
- `skills/revenium/scripts/hermes-report.sh` — current cron reporter: `set -uo pipefail` failure-tolerance posture, `REQUIRED_KEYS` marker contract, per-`muid` idempotency, `IFS='|'` pipe-delimited parsing, WR-01/D-34 pipe-safety sanitization, exit-code capture pattern (`cmd_output=$(... 2>&1) && cmd_exit=0 || cmd_exit=$?`).

---
*Pitfalls research for: adding agentic-job lifecycle tracking to the hermes-revenium metering skill (milestone v1.1)*
*Researched: 2026-05-14*
