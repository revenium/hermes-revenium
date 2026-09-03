# Comprehensive ROI live proof (ROI-12, ROI-13, plus D-06, D-12, D-13)

Whether one real tenant row can carry a configured revenue value, a cost side
that genuinely includes auxiliary usage, and a readable ROI, all three
together and not each separately — established 2026-09-03 against the same
host and pre-prod tenant Phase 49 and Phase 52 used (referred to here, as in
that record, as "the pre-prod multiplex test VM").

Unlike every prior live-proof phase in this project, this phase is not pure
observation. D-13 folded a concurrency fix — a bounded, fail-closed lock
around the auxiliary read-emit-append sequence — into this phase's own scope,
because it closes a known race on a billing path and this is the milestone's
last phase. This document is therefore observation **plus** one code change
on a billing path, and says so plainly rather than echoing the "observes
shipped behaviour, builds no new capability" framing every earlier live-proof
phase could honestly use.

## Verdict, up front — every criterion, in one table

| # | Criterion | Source | Verdict |
|---|---|---|---|
| 1 | A real tenant row shows a configured revenue value, a cost side including auxiliary usage, and a readable ROI — all three together, not each separately | ROADMAP criterion 1 / ROI-12 | **NOT CONFIRMED LIVE** — revenue value and ROI legs confirmed; the aux-inclusive-cost leg is not achievable on this tenant today, see finding below |
| 2 | The evidence is redacted, committed to a tracked `docs/` file, and pinned in `test_expected_files_exist` | ROADMAP criterion 2 | **CONFIRMED** — this file, at `docs/comprehensive-roi-proof.md`, pinned per Task 2 of this plan |
| 3 | Every limit is stated in the same document as the passes, following the `docs/live-tenant-proof.md` precedent | ROADMAP criterion 3 | **CONFIRMED** — this document's own shape, see "Limits" below |
| 4 | Feature-off behaviour is re-confirmed byte-identical on the live host | ROADMAP criterion 4 / ROI-13 | **CONFIRMED** — observable-behaviour equivalence, not literal byte-replay (a live session cannot be replayed); see caveat below |
| 5 | D-06: `jobs roi`'s read-surface finding (no `evidence_class`/`evaluator`/`confidence`) re-verified and re-dated | Carried item | **CONFIRMED**, re-dated 2026-09-03 |
| 6a | D-12: did the scoped guardrail rule's `currentValue` move? | Carried item (ROI-10) | **CONFIRMED** — moved `0 -> 0.024167`, an exact arithmetic match to the main-loop cost sum |
| 6b | D-12: did an auxiliary row fall inside the rule's scope, and move it? | Carried item (ROI-10) | **NOT CONFIRMED LIVE** — no aux row ever reached the tenant, see finding below |
| 7 | D-13: WINDOWS entry 5 concurrency fix (bounded, fail-closed lock on the auxiliary read-emit-append) | Carried item | **CONFIRMED** — discharged in plan 02, corroborated here by reading (not editing) the deployed, digest-verified code |

No criterion here is rounded up. Criterion 1's two confirmed legs do not round
the whole criterion up to CONFIRMED — the criterion's own wording is "all
three together, not each separately" — and D-12's second half is recorded as
awkward exactly because it is, not folded silently into the first half's
success. Every miss above is recorded in this same table as the passes, not
as a footnote, and each has its own section below carrying the investigation
between a heading that repeats the verdict and a closing sentence that
accepts it as the honest close.

## How each arm was scored

By read-back from the tenant, corroborated by a point lookup, never by exit
status. A `0` exit code is recorded where it occurred, but it carries no
evidentiary weight on its own — only `revenium jobs roi`, `revenium jobs
get`, and `revenium jobs outcome-history` returning the row, with the
expected fields, counted as confirmation. This is the same standard
`docs/live-tenant-proof.md` established, restated here rather than assumed.

Before any arm ran, the instrument itself was re-verified, not assumed still
current from a prior phase: credentials round-tripped
(`revenium guardrails budget-rules list --output json` returned 2 rows,
parsed successfully, without the stored CLI configuration ever being dumped
or printed); worst-case `PATH` resolution (with `$HOME/.local/bin` placed
first, matching `ensure_path`'s own construction) resolved `revenium` to the
real linuxbrew binary and not to the renamed Phase 28 test double, which does
not exist under the literal name `revenium` anywhere on `PATH`; and the
deployed tree was proven current, not merely present, by per-file sha256 in
both deployed locations — 55 files in the shipped skill tree and 15 files in
the separately loaded plugin copy Hermes actually imports, 0 mismatches in
either.

- **Deployed commit:** `c7f19ff64c8f862549f9c40e5143635edd951e4a`
- **CLI version:** `revenium 1.5.0 (0f5f3a7)`

## Criterion 1 — a real tenant row shows a configured revenue value, aux-inclusive cost, and readable ROI: NOT CONFIRMED LIVE

An induced probe (`hermes chat -Q --accept-hooks --yolo --max-turns 8`,
sentinel `PHASE56-PROBE-reverse-linked-list-ab01`) was driven under a
pre-declared attempt budget of up to twelve sessions in batches of four, with
a written stopping rule: stop as soon as one session produces a clean,
valued, `SUCCESS` assessment whose job also carries auxiliary rows. The very
first attempt qualified. Three more sessions in the same batch hit the
well-documented, unmodified evaluator confidence-rejection (`confidence
outside [0,1]: None`) — a 1-in-4 (25%) hit rate for this batch, squarely
inside the historically observed 70-90% rejection band. The evaluator, its
prompt, its token budget, and the valuation registry were not modified at
any point to raise this rate.

### The qualifying row, read back three ways

**Command: `revenium jobs roi reverse_linked_list_ab01_a3f0 --output json`**
```json
{
  "agenticJobId": "reverse_linked_list_ab01_a3f0",
  "agenticJobName": "Reverse a singly linked list in place",
  "agenticJobType": "feature_development",
  "executionStatus": "SUCCESS",
  "hasOutcome": true,
  "inputTokens": 19205,
  "outcomeCurrency": "USD",
  "outcomeType": "CONVERTED",
  "outcomeValue": 40.8,
  "outputTokens": 651,
  "roi": 878452.97,
  "totalCost": 0.004644,
  "totalTokens": 19856,
  "transactionCount": 2
}
```

**Command: `revenium jobs roi reverse_linked_list_ab01_a3f0`** (table form)
```
╭───────────────────┬───────────────────────────────────────╮
│ Metric            │ Value                                 │
├───────────────────┼───────────────────────────────────────┤
│ Job ID            │ reverse_linked_list_ab01_a3f0         │
│ Name              │ Reverse a singly linked list in place │
│ Type              │ feature_development                   │
│ Execution Status  │ SUCCESS                               │
│ Outcome Type      │ CONVERTED                              │
│ Has Outcome       │ true                                   │
│ Total Cost        │ $0.00                                  │
│ Outcome Value     │ $40.80                                 │
│ ROI %             │ 878452.97%                             │
│ Transaction Count │ 2                                      │
│ Input Tokens      │ 19205                                  │
│ Output Tokens     │ 651                                    │
│ Total Tokens      │ 19856                                  │
╰───────────────────┴───────────────────────────────────────╯
```

**Command: `revenium jobs get reverse_linked_list_ab01_a3f0 --output json`**
(`_links` block, which contains a team id, stripped before pasting here;
`reportedBy` redacted per this document's own convention)
```json
{
  "agenticJobId": "reverse_linked_list_ab01_a3f0",
  "created": "2026-09-03T13:37:04.279Z",
  "executionStatus": "SUCCESS",
  "hasOutcome": true,
  "id": "5o4qyk",
  "label": "Reverse a singly linked list in place",
  "outcomeCurrency": "USD",
  "outcomeMetadata": "{\"source\":\"cli\",\"value_low\":40.8,\"value_base\":48.0,\"value_high\":55.2,\"bounds_source\":\"derived\",\"evidence_class\":\"CUSTOMER_CONFIGURED\",\"evidence_class_authority\":\"valuation\",\"reportability_status\":\"reportable\",\"economic_mechanism\":\"incremental_revenue\",\"confidence\":0.9,\"model\":\"gpt-4o-mini\",\"inference_provider\":\"openai-api\",\"attribution_fraction\":0.15,\"attribution_basis\":\"PHASE56-PROBE: fixed policy value for a completed probe task, per Phase 56 D-02/D-05\"}",
  "outcomeReportedAt": "2026-09-03T13:37:30.855Z",
  "outcomeType": "CONVERTED",
  "outcomeValue": 40.8
}
```

**Command: `revenium jobs outcome-history reverse_linked_list_ab01_a3f0 --output json`**
```json
[
  {
    "executionStatus": "SUCCESS",
    "outcomeCurrency": "USD",
    "outcomeType": "CONVERTED",
    "outcomeValue": 40.8,
    "reportedAt": "2026-09-03T13:37:30.855Z",
    "reportedBy": "[redacted — tenant account identity]",
    "sequence": 1
  }
]
```

### The three figures, exactly as returned, tied to one job id

- **Revenue value:** `outcomeValue: 40.8` (USD) — this is `value_low` from the
  metadata blob, not `value_base` (`48.0`). The JSON `outcomeValue` field is
  what scores this row, not any other field in the metadata — a known
  rendering boundary, not a discrepancy (see the next section).
- **Cost total:** `totalCost: 0.004644` (USD) — main-loop only. See "The
  aux-inclusive-cost leg" below for what this figure does and does not
  include.
- **ROI:** `roi: 878452.97` (percent) — `jobs roi`'s own derived field.

All three are tied to the single job id `reverse_linked_list_ab01_a3f0`,
confirmed identical across `jobs roi`, `jobs get`, and `jobs
outcome-history`.

### A known rendering boundary, not a discrepancy

The JSON `outcomeValue` (`40.8`) is `value_low`, one of three bounds in the
outcome metadata (`value_low: 40.8`, `value_base: 48.0`, `value_high: 55.2`).
The table form renders the same field, `$40.80`. A reader comparing this
job's JSON `outcomeValue` against a *withheld* job's table rendering (see the
matched job below) is seeing a known rendering boundary — a withheld value
renders in the table as `$0.00`, indistinguishable from a genuine zero — not
a discrepancy in this job's own figures.

### The aux-inclusive-cost leg: why it is not achievable on this tenant today

**Phase 55's auxiliary metering has never successfully shipped a single row
to this live tenant.** While confirming that the qualifying job's auxiliary
row actually reached the tenant — not just that it existed locally — the
shipped, unmodified `hermes-report.sh` was found attempting and failing the
auxiliary emission for every session on this deploy, 100% reproducibly:

```
[2026-09-03T13:37:41Z] [WARN ] [revenium] Aux failed: session=20260903_133549_33bfdc label=aux_title_generation exit=4 output=
Error: Request failed (HTTP 400): Value 'AUX' is not valid. Allowed values: [CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER, TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO, VIDEO, IMAGE]
```

`AUX` is absent from the server's own allowed-values list. `OTHER` is
present. Grepping the whole metering log (beginning at this deploy's first
tick) for `"Aux failed"` returned **2176 matches, 0 successes** at
discovery time, growing to **4254** by the time the operator's checkpoint
closed — a measured **130 failed calls per minute**, with the count climbing
2824 -> 4254 while the checkpoint was open. `revenium-aux.ledger` has never
been created on this host, because the ledger only ever advances past a row
on a successful CLI call, and no call has ever succeeded here — which is
also why the count grows monotonically rather than plateauing: every tick
retries the entire accumulated, never-advanced set of rows from scratch.

**Why ROI-09/10/11 did not catch this:** those requirements were closed
against local fixtures, a pinned golden argv shape, and a CLI test double —
none of which validate an `operationType` value against a real server's
enum. This is a recurrence of this project's own recorded fixture-fidelity
failure mode ("fixtures pin what the TEST produces, not what production
sends"), now on a billing path rather than a metering-shape path.

**No code fix was proposed or applied here.** Changing `--operation-type
"AUX"` to `"OTHER"` (the accepted value nearest in spirit) is a real,
separate decision on a billing path with its own test-fixture and
golden-argv consequences, and editing the reporter to raise the pass rate
would have manufactured a result rather than measured one — exactly what
this plan's own prohibitions forbid. The pre-prod host's auxiliary pass has
instead been set to `REVENIUM_AUX_METERING=disabled` via the documented,
no-code off switch (`docs/migration-auxiliary-usage.md`, "Switching it
off"), so it stops retrying a call that cannot currently succeed. The code
defect itself remains unfixed and unchanged, pending that separate
decision.

**Criterion 1 verdict: NOT CONFIRMED LIVE.** The revenue-value and readable-ROI
legs are confirmed on the qualifying job above; the aux-inclusive-cost leg is
not achievable on this tenant today, for a reason orthogonal to the
well-documented evaluator hit rate. Accepted as the honest close.

## Toggle comparison (D-05) and the matched disabled-arm job

A matched job was driven with `REVENIUM_AUX_METERING=disabled` set via the
documented `${STATE_DIR}/env` off switch, sourced by the host's own
already-running per-minute cron under `set -o allexport` — no separate
manual cron invocation was used.

**Command: `revenium jobs roi flatten_nested_list_python_function_23b5 --output json`**
```json
{
  "agenticJobId": "flatten_nested_list_python_function_23b5",
  "agenticJobName": "Create a Python function to flatten nested lists",
  "agenticJobType": "feature_development",
  "executionStatus": "SUCCESS",
  "hasOutcome": true,
  "inputTokens": 19167,
  "outcomeCurrency": null,
  "outcomeType": "CONVERTED",
  "outcomeValue": null,
  "outputTokens": 692,
  "roi": null,
  "totalCost": 0.006055,
  "totalTokens": 19859,
  "transactionCount": 2
}
```

**Command: `revenium jobs roi flatten_nested_list_python_function_23b5`** (table form)
```
╭───────────────────┬──────────────────────────────────────────────────╮
│ Metric            │ Value                                            │
├───────────────────┼──────────────────────────────────────────────────┤
│ Job ID            │ flatten_nested_list_python_function_23b5         │
│ Name              │ Create a Python function to flatten nested lists │
│ Type              │ feature_development                              │
│ Execution Status  │ SUCCESS                                          │
│ Outcome Type      │ CONVERTED                                        │
│ Has Outcome       │ true                                             │
│ Total Cost        │ $0.01                                            │
│ Outcome Value     │ $0.00                                            │
│ ROI %             │ 0.00%                                            │
│ Transaction Count │ 2                                                │
│ Input Tokens      │ 19167                                            │
│ Output Tokens     │ 692                                              │
│ Total Tokens      │ 19859                                            │
╰───────────────────┴──────────────────────────────────────────────────╯
```

This is a fresh, live reproduction of `docs/roi-read-surface-ask.md`'s second
finding, dated today: the table renders this withheld value as `Outcome
Value $0.00` / `ROI % 0.00%` — visually indistinguishable from a genuine
zero — while the JSON form correctly shows `"outcomeValue": null` and
`"roi": null`. **The JSON `outcomeValue` is what scores this row as
withheld, not zero-valued.** `revenium jobs get`'s own `outcomeMetadata`
confirms this job's assessment was genuinely withheld by the skill's own
evidence-class/reportability gate (`"reportability_status":"candidate"`,
`"confidence":0.0`) rather than silently dropped by the tenant.

| | Job 1 (aux enabled) | Job 2 (aux disabled) |
|---|---|---|
| `totalCost` (`jobs roi` JSON) | `0.004644` | `0.006055` |
| `totalTokens` | 19856 | 19859 |
| Local `session_model_usage` aux row (`title_generation`) | `5.025e-05` | `5.04e-05` |
| Aux rows successfully shipped to tenant | **0** (all 3 shipment attempts for this job's own session failed with the `HTTP 400` above) | **0** (never attempted — feature disabled for this tick) |

**Exact decimal difference in `totalCost`: job 2 minus job 1 = `0.001411`** —
job 2 costs *more*, not less, despite both jobs carrying zero shipped
auxiliary rows. **This does not account for the auxiliary amount, and is
not claimed to.** The auxiliary amount metered against job 1 locally (since
nothing reached `revenium-aux.ledger`) was `$0.00005025` — the observed
`totalCost` difference runs in the opposite direction and is roughly **28x
larger** than the entire auxiliary amount that would have been at stake.
This gap is ordinary main-loop cost variance between two different,
non-replayable live tasks (different prompts, different token mixes,
different turn counts), visible directly in the near-equal `totalTokens`
(19856 vs 19859) alongside a real cost difference — the two jobs' token
compositions differ enough on their own to swamp an amount two orders of
magnitude smaller. See "The toggle-methodology noise floor" under Limits
below for the independent finding this implies about the comparison design
itself.

**ROI-13, scored independently of D-05's aux-inclusiveness claim:** the
disabled arm's own tick log carries **no** `AUXILIARY USAGE PASS` activity
of any kind for job 2 — no attempt, successful or failed — matching
`report_auxiliary_usage`'s own shipped early-return when the tunable
resolves to `disabled`. Main-loop metering shape is unchanged from job 1's
tick: both produced exactly one `GUARDRAIL` + one `CHAT` row per session,
same field names, same command shape.

```
[2026-09-03T13:43:02Z] [INFO ] [revenium] === Hermes Metering Reporter starting ===
[2026-09-03T13:43:02Z] [INFO ] [revenium] Reported: session=20260903_134134_f3634e muid=001a06781122087d633067b71d51f1120 task_type=implement_function_flatten_list op_type=GUARDRAIL in=9583 out=346
[2026-09-03T13:43:02Z] [INFO ] [revenium] Reported: session=20260903_134134_f3634e muid=001a0678112207aba2a4c13ceba88981c task_type=implement_function_flatten_list op_type=CHAT in=9584 out=346
[2026-09-03T13:43:29Z] [INFO ] [revenium] Outcome reported: agentic_job_id=flatten_nested_list_python_function_23b5 result=SUCCESS
[2026-09-03T13:43:29Z] [INFO ] [revenium] cost reconciliation this tick: classified=0.006055 (tokens=19859) unclassified=0.000000 (tokens=0) unallocated=0.000000 (tokens=0)
```

**Criterion 4 / ROI-13 verdict: CONFIRMED**, for the feature-off behavior
itself — zero attempts, unchanged main-loop shape — as observable behaviour
equivalence rather than literal byte-replay, since a live session cannot be
replayed to hold every other variable constant. **D-05's aux-inclusiveness
claim is separately NOT CONFIRMED LIVE**, because the "on" state never
successfully ships anything on this tenant either, so the comparison cannot
show a difference that never reaches the tenant on either side. The two
verdicts are not in tension: one is about the toggle's own effect
(confirmed), the other is about whether the "on" state does what it claims
against this tenant (not confirmed, live tenant API rejection).

## D-12 — the carried guardrail-scope item: 6a CONFIRMED, 6b NOT CONFIRMED LIVE

**Read via `revenium guardrails enforcement-rules get`, scoped rule (`ruleId
34252`, `metricType: TOTAL_COST`, `groupBy: AGENT`, filtered `AGENT IS
"Hermes"`):**

- **Pre-probe baseline:** `currentValue: 0` at `2026-09-03T13:34:35Z`
- **Post-probe reading:** `currentValue: 0.024167` at `2026-09-03T13:45:52Z`
- **Delta:** `0.024167`

Summing every main-loop-only `cost reconciliation this tick` line the
shipped cron logged for the five sessions this arm drove under agent
`Hermes`:

```
0.013784  (tick 13:37:41 — sessions 33bfdc, 7e7ac5, 6a12eb)
0.004328  (tick 13:39:39 — session 226489)
0.006055  (tick 13:43:29 — session f3634e / job 2)
--------
0.024167  == the exact currentValue delta
```

**Did the counter move? Yes** — by exactly the sum of main-loop costs, an
exact arithmetic match, not an approximate one. The rule's `AGENT`-only
scope is structurally correct for counting auxiliary rows too (per
`docs/migration-auxiliary-usage.md`'s rule-scope section, every auxiliary
row ships the same `--agent` value as its own session's main-loop
completion). **Did an auxiliary row fall inside that scope and move it?**
No auxiliary row was available to test this in practice, because none
reached the tenant — the same `AUX`-rejection root cause as criterion 1.
This half is **NOT CONFIRMED LIVE**, not because the scope itself is wrong,
but because the precondition (an auxiliary row actually reaching the
tenant) never held.

**D-12 verdict: 6a CONFIRMED, 6b NOT CONFIRMED LIVE.** Accepted as the
honest close on the awkward half.

## D-06 — the read-surface finding, re-verified and re-dated

Inspecting both captured `jobs roi` forms above (job 1 and job 2, JSON and
table) for `evidence_class`, `evaluator`, and `confidence`: all three are
**absent** from `jobs roi` in both JSON and table form, for both jobs. All
three appear only in `jobs outcome-history`'s `outcomeMetadata` blob.
`docs/roi-read-surface-ask.md`'s 2026-08-31 finding is **re-confirmed, live,
today (2026-09-03)**, on the current deployed commit (`c7f19ff`) and the
current CLI (`revenium 1.5.0`). No change on Revenium's side has occurred
since the original finding. See `docs/roi-read-surface-ask.md` for the
standing ask this re-verification updates.

## D-13 — the concurrency fix, corroborated

WINDOWS entry 5 (the auxiliary submission atomicity gap — an unlocked
read-ledger-baseline -> emit -> append sequence in `report_auxiliary_usage`
that could interleave with an out-of-band invocation and double-submit an
identical `--transaction-id`) was closed in plan 02 of this phase with a
bounded, fail-closed lock around the entire critical section, proven by a
two-racer concurrency test (`tests/test_phase56_aux_atomicity.py`) and a
fail-first mutation runner (`tests/mutation_verify_aux_atomicity.py`) that
demonstrates the test fails without the lock and passes with it. That work
is not re-litigated live in this document — a race window is not something
a single live run can prove closed by absence of collision. It is
corroborated here incidentally: while investigating the `AUX`-rejection
finding above, the currently-deployed, digest-verified
`report_auxiliary_usage` was read (not edited) and its lock-acquire code was
observed present and unchanged from plan 02's shipped commit.

**Criterion 7 / D-13 verdict: CONFIRMED** (discharged in plan 02, local
proof, corroborated here by reading the deployed code).

## Limits

- **One host, one pre-prod tenant, one deployed commit** — the pre-prod
  multiplex test VM, `c7f19ff64c8f862549f9c40e5143635edd951e4a`. Nothing here
  establishes production behaviour, and no claim is made about pricing or
  cost derivation beyond what this tenant actually charged.
- **The qualifying job was deliberately induced, not organic traffic.** Phase
  53's live arm ran 85 genuine live sessions and produced zero
  reportable/valued rows, so an induced probe under a written attempt budget
  and stopping rule was the only arm with a known success rate. The induced
  session should never be presented as organic tenant traffic — it was one
  of four sessions in a pre-declared batch, stopped at the plan's own
  written stopping condition.
- **The toggle-methodology noise floor.** Even had `AUX` been server-accepted,
  this specific toggle comparison — two different, non-replayable live jobs,
  not one job metered twice — has a noise floor of ordinary between-job
  main-loop cost variance (~28x the auxiliary amount at stake, and in the
  wrong direction) that would have swamped the effect it was built to
  isolate. This is an independent defect in the comparison design, not a
  casualty of the `AUX` rejection: a live, non-replayable-session toggle
  comparison of this kind would need either many more paired samples
  averaged together, or the locally-replayable fixture-level proof this
  project already has (Phase 55's own fixture harness), to distinguish a
  real aux contribution from ordinary job-to-job cost noise.
- **The `jobs roi` read-surface gap makes provenance invisible on that
  surface.** Re-confirmed above (D-06): a reader looking at `jobs roi` alone
  cannot tell a model-estimated figure from an operator-configured one, and
  cannot tell a withheld value from a genuine zero on the table form. Both
  gaps are read-surface limits, not defects in what was actually stored —
  `jobs outcome-history` carries the missing fields for the same job.
- **The D-12 scope limit.** Model and provider are per-row facts (Phase 55
  D-09), so a guardrail rule scoped on either would not automatically
  capture an auxiliary row the way a rule scoped only on `AGENT` does. Rule
  34252's `AGENT`-only scope is structurally correct for this host, but that
  correctness was never exercised in practice here, because no auxiliary row
  ever reached the tenant to test it.
- **The evaluator's live hit rate.** 1 clean, valued row in 4 attempts this
  batch — inside the documented 70-90% rejection band. The cause is not
  investigated here, deliberately; the evaluator was not modified at any
  point in this phase to raise the rate.
- **A planning-record defect, caught by reading source rather than trusting
  the plan.** `56-03-PLAN.md` Task 2 and `56-RESEARCH.md` Pattern 2 both
  describe `revenueCardKey` as needing to match the evaluator's
  model-inferred role — that is `rateCard`'s rule, not `revenueCard`'s.
  `skills/revenium/plugins/revenium-classifier/valuation.py:437-442` and
  `skills/revenium/references/config-schema.md:160-161` both establish that
  `revenueCardKey` is operator-bound, resolved from config, never from the
  model's own output (Phase 54 D-06) — deliberately, so the model can never
  be handed the selector on a revenue figure. The plan text was not amended;
  this is the corrective record.
- **This phase is not pure observation.** D-13's lock is a real code change
  on a billing path, folded into this phase's scope in the open rather than
  left as an unclosed race across the milestone boundary. See "D-13 — the
  concurrency fix, corroborated" above for what changed and what this
  document does and does not re-prove about it live.

## What DID work, stated with equal precision

The qualifying job reached `CUSTOMER_CONFIGURED` evidence class with
`outcomeValue: 40.8` and a readable ROI (`878452.97%`) on the very first
induced attempt — not the twelfth, not after retrying the evaluator, the
first one. The disabled arm's feature-off behavior was directly observed
from log absence, not inferred. The D-12 counter's movement was matched to
the last digit against independently-summed tick log lines. Two of this
criterion's three legs genuinely landed; the honest miss on the third does
not erase that.

## The environment

- **Host:** the pre-prod multiplex test VM (by role only; no address, key
  path, or tenant/team identifier appears anywhere in this file).
- **Deployed commit:** `c7f19ff64c8f862549f9c40e5143635edd951e4a`, deployed
  by `git archive` + `scp` + `install.sh`, deliberately avoiding `rsync`
  end to end. Currency proven by sha256 across both deployed locations (the
  shipped skill-tree copy and the separately loaded plugin copy Hermes
  actually imports), 55 + 15 files, 0 mismatches.
- **CLI:** `revenium 1.5.0 (0f5f3a7)`.
- **Worst-case `PATH` resolution:** re-run with `$HOME/.local/bin` placed
  first, matching `ensure_path`'s own construction. Resolved to the real
  linuxbrew binary, not to the renamed Phase 28 test double
  (`~/.local/bin/revenium-stub-phase28`), which remains present, untouched.
- Neither a credential value nor a tenant identifier appears anywhere in
  this file.

## Jobs created

Five job rows total across this phase's induction arms, all left in the
pre-prod tenant as the evidence behind this record, per this project's
standing convention that the rows stay:

- **Criterion 1 / qualifying job:** `reverse_linked_list_ab01_a3f0`
- **Rejected, same batch:** `write_palindrome_checker_function_e88c`,
  `merge_sorted_lists_function_creation_1715`,
  `word_frequency_function_creation_523b`
- **Disabled-arm matched job:** `flatten_nested_list_python_function_23b5`

A delete verb (`revenium jobs delete`) exists on this CLI. It is not used
here and is not recommended for these rows: deleting any row this document
cites would remove the evidence the document points at.

---
*Phase: 56-comprehensive-roi-live-proof*
*Recorded: 2026-09-03*
