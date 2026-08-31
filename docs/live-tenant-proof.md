# Live-tenant proof (LIVE-02 through LIVE-06, plus D-02 and D-03)

Whether the declaration-authority and operator-mechanism work — and the
sidecar carrier under both — behaves as shipped against a real tenant rather
than fixtures, established on 2026-08-31 against the same host and pre-prod
tenant Phase 49 used.

This phase **observes** shipped behaviour. It builds no new capability. Seven
criteria were in scope: the five ROADMAP names for LIVE-02 through LIVE-06,
plus two added in the open during planning (D-02, D-03) because they were
cheap on this specific host and otherwise would not have been.

**Verdict, up front — all seven, in one table:**

| # | Criterion | Source | Verdict |
|---|---|---|---|
| 1 | A sidecar assessment round-trips to a real tenant with provenance intact | LIVE-02 | **CONFIRMED** |
| 2 | A real tenant row carries an evidence class that is not the forced constant | LIVE-03 | **CONFIRMED** — valuation leg only, see limits |
| 3 | A real tenant row carries an operator-declared mechanism | LIVE-04 | **CONFIRMED** |
| 4 | The evidence is committed, redacted, to a tracked file with a pin | LIVE-05 | **CONFIRMED** — this file |
| 5 | Feature-off behaviour is re-confirmed byte-identical on the live host | LIVE-06 | **CONFIRMED** — deliberate toggle, see limits |
| 6 | Profile-scoped boundary provenance holds on a real multi-profile install | D-02 | **NOT CONFIRMED LIVE** — see finding below |
| 7 | The correction verb's live wire shape, against the ordinary verb's | D-03 | **CONFIRMED**, one axis unprobed |

Criterion 2's ROADMAP wording was conditional on Phase 50 building. Phase 50
shipped and the won't-fix trigger named in that wording did not fire, so
criterion 2 stands as originally written; this file scores it as written,
not as a fallback.

No criterion here is rounded up. Criterion 6 is recorded as a miss with its
reason, in the same table as the passes, not as a footnote.

## How each arm was scored

By read-back from the tenant, corroborated by a point lookup, never by exit
status. This project's own instrument-trust history is the reason: on
2026-08-19 the Revenium API returned success and persisted nothing for
roughly seven hours. A `0` exit code is recorded where it occurred, but it
carries no evidentiary weight on its own — only `revenium jobs
outcome-history` and `revenium jobs get` returning the row, with the
expected fields, counted as confirmation.

Before any arm ran, the instrument itself was re-verified: credentials
authenticate against the pre-prod tenant, worst-case `PATH` resolution finds
the real `revenium` binary ahead of the renamed Phase 28 test double, and a
throwaway read-back gate job round-tripped correctly. This repeats Phase
49's V1 check rather than assuming it still holds.

## LIVE-02 — sidecar round-trips with provenance intact

Two real sidecar records, produced by genuinely driven `hermes chat`
sessions and the deployed classifier's real call to `gpt-4o-mini` via
`openai-api`, were metered by the shipped, unmodified `cron.sh` and read
back field-by-field against the server's returned metadata.

- `write_dedupe_function_2d1d` — `evidence_class_authority: evaluator` (no
  boundary configured yet; the natural control).
- `implement_max_subarray_function_85d1` — `evidence_class_authority:
  valuation` (after the rate card, below).

Every provenance field survived: `evaluator`, `evaluator_version`, `model`,
`evidence_class`, `reportability_status`, `confidence`,
`economic_mechanism`, `double_counting_group`, `inference_provider`,
`inference_address_class`, `evidence_class_authority`, and the four version
counters (`assessment_schema_version`, `taxonomy_version`, `prompt_version`,
`policy_version`) — all echoed back byte-exact for both jobs.

Two fields looked, on a naive comparison, like drops: `supplied_costs` was
absent from the returned metadata where the sidecar showed an empty `{}`,
and `cost_coverage` came back with two of its four sub-lists missing. Both
are the shipped forwarder's own documented compaction — `hermes-report.sh`
only emits `supplied_costs` when the rebuilt dict is non-empty, and only
keeps a `cost_coverage` sub-list key when that filtered sub-list itself is
non-empty. Re-scored against the correct expectation (compacted, not
literal), both fields survived exactly as designed. Neither is a round-trip
failure.

The entire value family (`value_low`, `value_base`, `value_high`,
`bounds_source`, `currency`, `estimated_value`, `assumptions`, `net_value`)
was correctly withheld on both jobs — every record here has
`reportability_status: candidate`, not `reportable`, because
`experimentalReportEstimates` was never set anywhere in this phase. That is
the correct, deliberate behaviour of the shipped gate, not a limitation of
this arm.

`metadata_truncated` was absent from both returned payloads, consistent
with measured sizes (584 and 583 bytes) far under the client-side
`_METADATA_CEILING_BYTES = 4096` ceiling Phase 49 established as
conservative.

**LIVE-02 verdict: CONFIRMED**, for both jobs, no provenance field dropped
or altered.

## LIVE-03 — a non-forced evidence class, on a real tenant row

Before any boundary was configured, `write_dedupe_function_2d1d`'s row
correctly carried the forced constant: `evidence_class:
MODEL_ESTIMATED_DEMO`, `evidence_class_authority: evaluator`. That row
serves as the control for what follows.

A genuine operator rate card was then written —
`llmOutcomeEvaluation.rateCard = {"software developer": 95.00}` — keyed on
the role the first driven session actually inferred (`software developer`,
observed before any card existed), with `boundaries.valuation` pointed at
`rate_card_valuation_fixture`. The rate was chosen deliberately different
from the evaluator's own unprompted $100/hr assumption, specifically so a
match would prove the card was consulted rather than merely agreeing by
coincidence.

The next matching session's record, read back from the tenant:

```
evidence_class: "CUSTOMER_CONFIGURED"
evidence_class_authority: "valuation"
```

Not the forced constant, and the authority names the boundary that actually
decided, on the real tenant row — not inferred from the local sidecar. The
returned `estimated_value` is withheld (candidate, not reportable), but the
local sidecar already confirmed the boundary produced `95.0` (the card's
number, not `2.0 hrs × $100/hr = $200`, which the local `value_base` field
still separately shows), before the reportability gate withheld it from the
wire.

**Why this configuration is the honest one, and the alternative would not
have been:** LIVE-03 only requires a non-forced evidence class, and two
fixtures could have supplied one. Writing real rates into
`config["rateCard"]` **is** the configuration being claimed — the claim is
true by construction. The other available route, a confirmation-workflow
fixture that resolves to `CUSTOMER_CONFIRMED`, would instead have recorded
an *external fact* — that a customer confirmed something — by writing a job
id into config, without any customer having confirmed anything. That would
have been a false evidence claim on a billing-adjacent record, precisely
what this project's evidence-boundary work exists to prevent. The
rate-card route was used for that reason, not for convenience.

The rate card's own honest limit: configuration establishes an *approved
rate*, not actual hours worked. The hours side of the arithmetic still
comes from the evaluator's own assumptions, unverified by any boundary.

**LIVE-03 verdict: CONFIRMED**, scoped to the valuation leg only — see "What
this does not establish," item 1.

### The model's real hit rate on this host (must not be read past)

Across all 12 sidecars this phase's driven sessions produced (7 extra
retries beyond the two designated results, all real, none constructed): **8
`rejected`, 2 `abstained`, 2 clean.** `gpt-4o-mini`, called with
`agent.reasoning_effort: none` (an unplanned host-config change, see below),
omitted the evaluator's required `confidence` field on most calls, each
logged verbatim by the shipped classifier as `rejected assessment,
confidence outside [0,1]: None`. The two `abstained` records were trivial
"reply PONG" sessions that correctly declined to price nothing. The shipped
prompt was deliberately **not** patched to chase a higher hit rate — this
plan's own rule forbids editing the thing being measured, and the arm
worked without it. The two clean, fully-valued records above are real and
correctly processed end to end, but they are not the modal outcome on this
host as configured; the model satisfies the shipped prompt roughly one time
in six.

A related observation, not a defect: rejected records still carry
`evidence_class`/`evidence_class_authority` (visible in the sidecar even
where `estimated_value` is `None`). This follows directly from the design —
the class is the boundary's `register()`-time declaration, and the shipped
classifier deliberately keeps provenance when a value is withheld — but no
test surfaced it before this live run, and a reader could otherwise mistake
a valueless, rejected row for a stronger claim than it is.

Full inventory (job id / outcome / class / authority / role / hours / rate
/ value), the two designated results marked:

| job id | outcome | evidence_class | authority | role | hrs | rate | value |
|---|---|---|---|---|---|---|---|
| `simple_response_pong_cf47` | abstained | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `respond_with_pong_a266` | abstained | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `dispatch_email_validation_function_e626` | rejected | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `token_bucket_rate_limiter_implementation_e7dc` | rejected | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `run_unit_tests_for_rate_limiter_56e3` | rejected | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `unit_tests_for_rate_limiter_5bfa` | rejected | MODEL_ESTIMATED_DEMO | evaluator | — | — | — | — |
| `write_dedupe_function_2d1d` | clean | MODEL_ESTIMATED_DEMO | evaluator | software developer | 2.0 | 100.0 | 200.0 (LIVE-02 result) |
| `flatten_nested_list_creation_dbb6` | rejected | CUSTOMER_CONFIGURED | valuation | — | — | — | — |
| `write_is_palindrome_function_a0fd` | rejected | CUSTOMER_CONFIGURED | valuation | — | — | — | — |
| `reverse_words_function_creation_fdf4` | rejected | CUSTOMER_CONFIGURED | valuation | — | — | — | — |
| `implement_max_subarray_function_85d1` | clean | CUSTOMER_CONFIGURED | valuation | software developer | 2.0 | 100.0 | 95.0 (LIVE-02/03/04/D-03 result) |
| `count_vowels_function_creation_6da2` | rejected | CUSTOMER_CONFIGURED | valuation | — | — | — | — |

**An unplanned host change this record must carry:** `agent.reasoning_effort`
was changed from `medium` to `none` in the host's `config.yaml` alongside a
necessary, separate fix (`model.provider: openai -> openai-api`, since bare
`openai` is a Hermes CLI alias to OpenRouter, unconfigured on this host).
The `reasoning_effort` change was not named in any plan and was not
reported until it was found by diffing against a wave-1 backup. It most
likely made `gpt-4o-mini` viable on this host at all — `medium` triggers a
`reasoning.effort` parameter the model rejects outright. Every
model-behaviour claim in this section, including the hit-rate finding, is
conditioned on this change.

## LIVE-04 — an operator-declared mechanism, on a real tenant row

`implement_max_subarray_function_85d1` — the same job LIVE-03's verdict
rests on — was corrected through the shipped `correct-assessment.sh`,
mechanism-only (no `--value`), declaring `risk_avoidance`: one of three
mechanisms (`quality_decision_improvement`, `risk_avoidance`,
`incremental_revenue`) the shipped classifier marks operator-only. An
evaluator session can never produce this label itself, which is why it was
chosen — the row's origin is unambiguous.

Previewed first (`--dry-run`), then shipped for real. Read back via
`revenium jobs outcome-history` at `2026-08-31T17:06:54Z`:

```
Revision 1 (original):  evidence_class=CUSTOMER_CONFIGURED  authority=valuation  economic_mechanism=labor_substitution
Revision 2 (correction): economic_mechanism=risk_avoidance   reason="PHASE52-ARM-MECH-CORRECTION-SENTINEL ..."
```

Two revisions, both present, correction newest and superseding rather than
overwriting — the original line's on-disk digest is unchanged before and
after the correction. `economic_mechanism: risk_avoidance` reached the
server exactly as declared.

**LIVE-04 verdict: CONFIRMED.**

## Criterion 7 (D-03) — `jobs outcome-update`'s live wire shape

`jobs outcome-update`, the correction verb, had never been exercised live
in this project before this phase; Phase 49 exercised only the ordinary
`jobs outcome` verb. Both were compared on the same tenant.

- **Flag surface.** Disjoint at the required flag by design: `jobs outcome`
  requires `--result`; `jobs outcome-update` requires `--reason`. Both
  share `--metadata`, `--outcome-currency`, `--outcome-type`,
  `--outcome-value` as optional flags. Global flags identical on both.
- **Argv.** Read from the deployed, sha256-confirmed-current scripts, not
  reconstructed from memory. `correct-assessment.sh`'s construction and
  `hermes-report.sh`'s construction both matched their respective pinned
  golden fixtures, accounting for each golden's own documented
  conditionality (this arm's mechanism-only correction correctly omitted
  `--outcome-value`/`--outcome-currency`, which the value-bearing golden
  pins as present — a different, equally legal arm, not a divergence).
- **Metadata, key-by-key.** All 7 keys sent in this correction's metadata
  (`assessment_schema_version`, `sequence`, `prior_value_low`,
  `prior_value_base`, `prior_value_high`, `prior_currency`,
  `economic_mechanism`) came back byte-exact — parsed-dict equality `True`,
  the same terms Phase 49 established for the ordinary verb.
- **Failure posture — unprobed.** Both the preview and the real invocation
  succeeded (exit 0 both times) on this arm; no rejection occurred
  naturally, and per this plan's own prohibition none was manufactured to
  force one. Whether a rejected `jobs outcome-update` call produces the
  same class of error as a rejected `jobs outcome` call remains an open
  question.

**A stronger result than "compared and unchanged":** the correction's
returned metadata does not merely leave `evidence_class` and
`evidence_class_authority` unchanged from revision 1 — it never restates
either key at all. `correct-assessment.sh`'s metadata construction has no
`evidence_class` key in its vocabulary in the first place, by design. Class
membership for this job continues to live solely on the original revision.
This is a stronger guarantee against class-drift than "asserted and found
equal" would have been, and the record should carry that distinction
rather than the looser phrasing.

A second, incidental finding worth recording: the API's own top-level
revision `sequence` (2, for this correction, 1-indexed across all revisions
of the job) is a different counter from the `sequence` field embedded
*inside* the correction's own metadata (1, `correct-assessment.sh`'s local
count of corrections only). Both are correct; a reader who conflates them
will misread the history.

**Criterion 7 verdict: CONFIRMED**, with the failure-posture axis
explicitly unprobed.

## LIVE-06 — feature-off, re-confirmed on the live host

**This was a deliberate toggle, not an as-found untouched install.** The
gate (`llmOutcomeEvaluation.enabled`) was found `true` on this host before
this phase touched anything — pre-existing, not written by any earlier
plan — and was set to a literal JSON `false` by this phase, recorded
explicitly as that state change. There was no untouched feature-off
baseline available on this host, and the record does not claim otherwise.

With the gate off and no `boundaries` object anywhere in config, two real
`cron.sh` ticks were run. A job-outcome row was produced by driving one
real classified session and, because this host carries no usable live LLM
credentials for genuine job inference, hand-appending one `kind:"job"`
marker line in the shipped classifier's own frozen record shape — the
unmodified, shipped `hermes-report.sh` then performed job creation,
outcome shipping, and metadata construction for real from that marker,
exactly as it would for a genuinely inferred job.

Read back from the tenant (`p52-arm2-20260831151613`):

```
outcomeMetadata: {"source": "cli"}
```

`source` is one of the two base metering keys the reporter always sends and
is explicitly excluded from both enrichment-family tuples. The returned key
set's intersection with both the 10-key value family and the 14-key
provenance family, extracted from the deployed script's own source, was
empty. No enrichment key of any kind reached the wire.

A second tick, run against unchanged session state, produced zero new
ledger lines and left every marker file byte-identical (whole-snapshot diff
across config, all three ledgers' size/line-count/sha256, and every marker
file's sha256) — idempotent, as required.

**LIVE-06 verdict: CONFIRMED**, with the toggle disclosed as deliberate and
the job-classification decision itself not exercised for real (see limits,
item 6).

## Criterion 6 (D-02) — profile-scoped boundary provenance: NOT CONFIRMED LIVE

Two real Hermes profiles (differing `boundaries` configuration, one with a
genuine rate-card boundary, one with none) were built on the host, each
running the deployed classifier plugin proven current by per-file **sha256
— 0 mismatches, 15 files each** — presence was not treated as currency.
`gateway.multiplex_profiles: true` was genuinely activated and confirmed
from the gateway's own log: one process serving three profiles (`default`,
`p52alpha`, `p52beta`). Two real, non-mock sessions were driven through the
`api_server` platform, one per profile, each a genuine `gpt-4o-mini` call
with a real tool call, each correctly isolated to its own profile's
`state.db`.

The condition criterion 6 asks about — whether a classified record can be
misattributed across profiles — was never reached, for two compounding
reasons:

1. The classifier's per-session path resolver (`_paths_for_session`)
   matches session ids shaped `agent:<profile>:...`. This deployed Hermes
   install's `api_server` platform mints ids shaped `api-<hex>` instead.
   Neither profile's session id matched, so both sessions' markers landed
   in the same default, process-level directory — **identically for both
   profiles.**

   **This symmetry does not rule out a provenance leak, and an earlier
   draft of this document wrongly said it did.** Because both sessions fell
   back to process-level paths, *neither profile's own boundary
   configuration was ever consulted*. The code path capable of
   misattributing a record across profiles did not execute. Nothing was
   therefore established about whether profile isolation holds: this is
   absence of evidence, not evidence of absence.

   What the symmetry does establish is narrower, and worth stating only as
   that: the observed behaviour is not *itself* an instance of the defect —
   no record named a boundary belonging to a different profile, because no
   record named a profile-specific boundary at all. A misattribution
   defect would have a direction, one profile's record landing under the
   *other's*. What was observed has no direction because the resolver never
   engaged. That is a detection miss, and it leaves criterion 6's actual
   question untouched.
2. `api_server` completions are stateless and never populate `ended_at` on
   the session row, so the outcome-evaluation logic criterion 6 targets
   never runs at all on this route. No sidecar was produced for either
   profile.

No further engineering was applied to force the condition — no session-id
shape was fabricated, no narrower unit-style substitute was presented as a
live result, and no tenant row was written for this arm. This was a
decision, not an oversight: forcing the condition would have produced a
result about a fabricated code path, not about what actually runs.

**The finding, stated with its limit, not without it.** This does *not*
establish that the `_paths_for_session` regex can never match a real
session id anywhere on this deployed Hermes version. Only one platform
(`api_server`) was exercised, on one host, in this run. A code read of the
shared session-id generator suggested every platform mints ids the same
way; that generalization is explicitly not claimed here, because the fleet
ran real `agent:<profile>:`-shaped sessions in phases 28–30, on a
*different* host, at a different point in this project's history. What is
established: on this host, at this deployed commit, via the `api_server`
multiplex route, no real session id matched, and the correction branch
`b4c3b63` added was never exercised. Filed as its own todo,
`paths-for-session-regex-may-never-match`, severity high — not folded
silently into "could not reach multiplex."

### Amendment 2026-08-31 — the root cause, found after the phase closed

Everything above stands as the record of what the arm established while it ran.
This block records what was learned afterwards, during the post-phase cleanup of
the same host, and it changes the *diagnosis* — not the verdict.

The blocker is not a drifted id shape. It is a **namespace mismatch**:
`agent:<ns>:` is the session-**key** namespace, it is alive and well in this
Hermes version, and it has never been the session **id**. `_paths_for_session`
matches a key-shaped regex against an id, so it cannot match — anywhere, on any
platform, on this version.

From the deployed Hermes' own source (`gateway/session.py:1070-1087`, its
docstring verbatim):

> The historical key format is `agent:main:<platform>:<chat_type>:...` where
> `main` is a static namespace literal (**NOT** a branch name — branching keys
> off `session_id`, not this slot).

with the default profile mapping to `agent:main` and a named profile `coder` to
`agent:coder`; `gateway/run.py:19947` assembles the rest. What the classifier is
handed is the other identifier — `gateway/run.py:12753` calls
`finalize_session(session_id=entry.session_id, …)`, i.e. `sessions.id`.

A live capture of every session on the host, taken before the profiles were torn
down, widens the original one-platform observation to four sources:

| database | rows | `sessions.id` shape | source |
|---|---|---|---|
| `state.db` | 32 | `20260831_162501_ccfdf5` | cli(26), subagent(4), cron(2) |
| `profiles/p52alpha/state.db` | 1 | `api-1b852ab4523500e5` | api_server |
| `profiles/p52beta/state.db` | 1 | `api-ca0b6a3eee148a5e` | api_server |

None is `agent:`-prefixed — including the `cli` and `subagent` sources the
ordinary metering path runs on daily, not just the `api_server` route the arm
exercised.

**The fix is not "teach the regex the new shape."** There is no id shape to
learn; the profile is not in the id. It is in the row: `sessions.profile_name`,
populated correctly on exactly the sessions where resolution failed —
`p52alpha` and `p52beta` on the two profile databases, `NULL` on the
process-level one, which is the right answer for a non-multiplexed home. A
`session_key` column exists too, but 0 of 34 rows carry a non-null value on this
version, so the key is not persisted here and cannot be the fix's source.

**What this amendment still does not claim.** That the same holds on other
Hermes versions or on the phases 28–30 fleet host. One host, v0.20.1
(2026.8.13), four session sources. The strong hypothesis — that the fleet
observation was of session *keys*, and that the regex was written against keys
and applied to ids from the start — is a hypothesis about a host not re-examined
here, not a measurement.

The consequence for `b4c3b63`, stated at the scope actually measured: on this
v0.20.1 host the `paths`-threading fix is correct but **inert**, and per-profile
marker routing and per-profile boundary provenance are both silently disabled
*there*. Whether that extends to any other multiplexed install depends on
whether its Hermes mints ids from the same namespace — which is the open
question above, not a result. An operator seeing profile-routing failures on a
different version or host should not assume this is the cause without checking
their own `sessions.id` shapes first. Recorded in full in the todo
`paths-for-session-regex-may-never-match`, which this amendment supersedes as
the durable copy.

**Criterion 6 verdict: NOT CONFIRMED LIVE.** Accepted as the honest close.

## What this does not establish

1. **One leg of four, for LIVE-03.** The proof exercises the **valuation**
   leg of the four-leg precedence walk
   (`evidence > valuation > classification > evaluator`) only. The evidence
   leg's live behaviour is unproven — `confirmation_workflow_evidence_fixture`
   was never configured anywhere in this phase, by design. The walk's
   priority ordering, what happens when two boundaries' declarations
   compete, remains proven by test alone, not by this run.
2. **The model satisfies the shipped prompt about a fifth of the time.**
   Across all 12 sidecars this phase produced on `gpt-4o-mini`: 8
   `rejected`, 2 `abstained`, 2 clean. The shipped evaluator prompt was
   deliberately not patched to raise this rate. Two clean, fully-valued
   records are real and correctly processed, but they are not
   representative of a typical call on this host as configured — anyone
   reading the two successful records above should read them against this
   ratio, not as the norm.
3. **A rejected record still carries the evidence class.** Confirmed live:
   `abstention_reason: "rejected"` with `estimated_value: None` still
   carries `evidence_class: CUSTOMER_CONFIGURED` /
   `evidence_class_authority: valuation`. Recorded as an observation, not a
   defect — it follows directly from the class being a boundary's
   `register()`-time declaration, and the shipped classifier's deliberate
   choice to keep provenance even when a value is withheld. No test
   surfaced this before this live run.
4. **An undocumented host change underlies every model-behaviour claim
   here.** `agent.reasoning_effort` was changed from `medium` to `none`,
   unplanned, alongside a necessary provider-name fix, and found only by
   diffing against a pre-phase config backup. Every claim in this file
   about what `gpt-4o-mini` does or does not do on this host is conditioned
   on that change.
5. **Criterion 6's finding is scoped, not universal.** It does not
   establish that the classifier's per-session path regex is dead code
   everywhere. One platform (`api_server`) was exercised, on one host, at
   one deployed commit. The fleet ran matching-shaped session ids on a
   different host in an earlier phase of this project. **See the
   2026-08-31 amendment in the criterion 6 section**: the root cause is now
   known to be a session-key-versus-session-id namespace mismatch, and the
   observation is widened to four session sources — but it is still one
   host at one Hermes version, and this limit stands as written.
6. **LIVE-06's feature-off state was a deliberate toggle, found `true`
   first.** There is no untouched, as-found feature-off baseline on this
   host, and there never was one for this phase to capture. The
   job-classification decision itself was also not genuinely exercised
   under feature-off — this host has no usable live LLM credentials for a
   real classification, so the job-outcome surface was exercised via a
   real cron tick against a hand-appended marker in the classifier's own
   frozen record shape, not via a genuinely LLM-inferred job.
7. **One host, one tenant, pre-prod.** A single multiplex test VM, a
   single pre-prod tenant, one deployed commit (`35d7c683`). Nothing here
   establishes production behaviour, and cost is $0 on this tenant by
   decision — no claim is made about pricing or cost derivation.

## The credential incident

While diagnosing an `api_server` platform credential during the criterion-6
arm, a locally-generated, loopback-only `API_SERVER_KEY` test credential
was echoed into an executor's own tool output by a `cat -A` diagnostic
before it had been used in any live request. It is not a Revenium or
OpenAI credential — it authenticates only a local, loopback-bound HTTP
listener used to drive test sessions on this host. It was rotated
immediately, and its value is not reproduced anywhere in this file or in
any other Phase 52 artifact. All Phase 52 artifacts were independently
scanned for secret-shaped strings afterward: clean.

## The environment

- **Host:** the same multiplex test VM Phase 49 used — a clean box, no
  shared tenant.
- **Deployed commit:** `35d7c6830b40f1528514797a32ec17ff4a68199b`, deployed
  by `git archive` + `scp` + `install.sh`, deliberately avoiding `rsync`
  end to end. Currency proven by sha256 across both deployed locations (the
  shipped skill-tree copy and the separately loaded plugin copy Hermes
  actually imports), 39 + 12 files, 0 mismatches.
- **CLI:** `revenium 1.5.0 (0f5f3a7)`.
- **Worst-case `PATH` resolution:** re-run with `$HOME/.local/bin` placed
  first, matching `ensure_path`'s own construction. Resolved to the real
  linuxbrew binary, not to the renamed Phase 28 test double
  (`~/.local/bin/revenium-stub-phase28`), which remains present, renamed
  aside, and untouched — not restored, not deleted.
- Neither a credential value nor a tenant identifier appears anywhere in
  this file.

## Jobs created

Fourteen job rows total across this phase, all left in the pre-prod tenant
as the evidence behind this record, per this project's standing convention
that the rows stay:

- **Instrument gate:** `p52-gate-20260831-145606`
- **LIVE-06 (feature-off):** `p52-arm2-20260831151613`
- **LIVE-02 / LIVE-03 (12 sidecars, all metered, 2 designated as scoring
  results):** `simple_response_pong_cf47`, `respond_with_pong_a266`,
  `dispatch_email_validation_function_e626`,
  `token_bucket_rate_limiter_implementation_e7dc`,
  `run_unit_tests_for_rate_limiter_56e3`, `unit_tests_for_rate_limiter_5bfa`,
  `write_dedupe_function_2d1d`, `flatten_nested_list_creation_dbb6`,
  `write_is_palindrome_function_a0fd`, `reverse_words_function_creation_fdf4`,
  `implement_max_subarray_function_85d1`, `count_vowels_function_creation_6da2`

`implement_max_subarray_function_85d1` carries two revisions: revision 1 is
the original outcome LIVE-02/LIVE-03 score against (`evidence_class:
CUSTOMER_CONFIGURED`, `authority: valuation`, `economic_mechanism:
labor_substitution`); revision 2 is the LIVE-04 correction
(`economic_mechanism: risk_avoidance`, no evidence-class key at all — see
criterion 7 above). Every other job carries exactly one revision.

No row was written for criterion 6 — the arm never reached metering.

A delete verb (`revenium jobs delete`) exists on this CLI. It is not used
here and is not recommended for these rows: deleting any row this file
cites would remove the evidence the file points at.

---
*Phase: 52-live-tenant-proof*
*Recorded: 2026-08-31*
