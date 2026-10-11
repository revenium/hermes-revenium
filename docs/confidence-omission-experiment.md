# Can a prompt change make the evaluator supply confidence? The Phase 67 experiment

[← Back to the docs index](README.md)

This record is the working file for one requirement of the Trustworthy ROI
Numbers milestone (TRU-03): the outcome evaluator sometimes returns a
response with no usable `confidence`, the validator rejects the whole
assessment, and the job's Job Value stays empty. TRU-03 asks whether a
prompt-level change to the evaluator contract can make the model supply the
field, or, failing that, whether the absence can be written up as a documented
limit. It accepts an honest limit. It does not accept a silent workaround: a
missing `confidence` is never defaulted, inferred or waved through.

The record measures prompt-level changes against the omission rather than
mining logs again. It opens with the baseline, preserved from logs that were
about to rotate away. The forward proof on the reference host (TRU-07) is not
this phase's. It belongs to Phase 70 and runs after deployment. The replay ran, and its pre-registered rule computed
`CLEARED — arm A1, already deployed`: today's prompt omits `confidence` on 0 of
300 replayed arcs where the prompt without the role list omitted it on 133 of
300, so no further prompt change ships. Nothing under `skills/` changed: this
record and the tests that guard the code it must not touch are the only
additions.

## Verdict, up front — every criterion, in one table

| # | Criterion | Source | Verdict |
|---|-----------|--------|---------|
| 1 | At least one prompt-level change to the evaluator contract is tried and measured against the omission-rate baseline below | TRU-03 / SC1 | CONFIRMED — the deployed prompt (PR #140) was measured against the prompt without its role list: 133 of 300 omitted under the second, 0 of 300 under the first |
| 2 | Either the omission rate measurably drops and the mechanism is explained here, or this record states plainly that no prompt change tried moves it, and why | TRU-03 / SC2 | CONFIRMED — the rate dropped and the mechanism is explained (as a hypothesis; see The mechanism) |
| 3 | No change to `LABEL_RE`, `TRIVIAL_BLOCKLIST`, the reportability gate or evidence-class promotion | SC3 | CONFIRMED — the contract pin tests pass and nothing under `skills/` differs from the phase start |

**TRU-03 status:** satisfied — today's prompt (PR #140, already deployed) lowered the conditional omission rate on z-ai/glm-5.2 from 133/300, under the prompt the glm-5.2-era arcs saw, to 0/300 under the pre-registered rule; no further prompt change ships.

**Validity gate:** PASSED

**Decision rule outcome:** CLEARED — arm A1, already deployed

## The baseline

The baseline is the share of evaluated arcs that reached the confidence check
and lost their assessment there because the response carried no usable
`confidence`. It is re-derived from a frozen copy of the reference host's
retained `agent.log*` files, joined to the job-assessment sidecar for the model
that served each arc.

| Served model | Valued | Valuation abstained (role miss) | Confidence omitted | Reached the confidence check | Omission rate (Wilson 95%) |
|--------------|-------:|--------------------------------:|-------------------:|-----------------------------:|---------------------------:|
| `z-ai/glm-5.2` | 55 | 25 | 22 | 102 | 21.6% (14.7% to 30.5%) |
| `z-ai/glm-5.3-flash` | 20 | 5 | 0 | 25 | 0.0% (0.0% to 13.3%) |
| Anthropic models (other sessions) | 1 | 7 | 0 | 8 | 0.0% (0.0% to 32.4%) |

**The window.** The retained logs run from 2026-09-25 to 2026-10-07. The
`z-ai/glm-5.2` arcs in them fall between 2026-09-25 and 2026-09-30, the
`z-ai/glm-5.3-flash` arcs between 2026-09-30 and 2026-10-06, and the
Anthropic-model arcs between 2026-09-26 and 2026-10-04. The sidecar shows
`z-ai/glm-5.2` serving evaluations from 2026-09-18, so the retained logs cover
only the later part of that era: earlier omissions had already rotated out.

**How the causes are split: log-line pairing.** Two different failures leave
the same empty Job Value. The sidecar cannot tell them apart. Every one of
its `rejected` rows (141 of 141) lacks the `assumptions` field, because the
sidecar omits that field on every abstention path. So a rejected row says only
that the arc failed, never why. The log can say why, because each cause logs
its own line before the shared `outcome evaluation rejected` line, and the
session id is the first bracketed token of every classifier line. The
derivation reads the four files oldest rotation first and pairs lines per
session id:

- a `confidence outside [0,1]` line followed by a rejection for the same
  session is a confidence omission;
- a `valuation implementation ... invalid or out-of-bounds value` line
  followed by a rejection is a role miss;
- the rare bound-exceeded and non-numeric hours or rate lines are counted
  separately (none occurred in the retained window), and a rejection with no
  preceding cause line would count as unattributed (none occurred either);
- an `outcome evaluated` line is a valued arc.

The validator's gate order is what makes the split clean. It checks the
mechanism, then the hours and rate, then `confidence`, and only afterwards the
valuation and its role lookup. An arc whose confidence was omitted therefore
never reaches the role check. The two causes are disjoint per arc, but they
compete for the same population of arcs.

**The denominator.** It is the arcs that reached the confidence check: valued,
plus valuation-abstained, plus confidence-omitted. An arc that stopped at the
mechanism gate or at the hours and rate gate never had a chance to omit
`confidence`, so counting it would dilute the rate with arcs that could not
have shown the defect. Excluding them removes no confidence omissions.

**The earlier milestone figure of 26 does not reproduce.** The milestone brief
cited 26 rejections. The retained logs give 22 confidence omissions, all under
`z-ai/glm-5.2`. The difference is in no retained file, so the 26 cannot be
re-derived and is not repeated here as a measured figure.

**Known Risk 1: fixing the omission makes the role miss more visible.** An arc
rescued from the confidence gate now reaches the valuation boundary, and some
of those will abstain on a role the rate card does not list. So Job Value fill
rate can stay flat while the omission rate falls. The Job Value fill rate is
never this record's metric. Each cause is measured by its own log line.

**Today's prompt is not the prompt `z-ai/glm-5.2` saw.** The glm-5.2 window
closes on 2026-09-30. PR #140, which added the approved-role list to the
evaluator prompt, merged on 2026-10-03. Those arcs were evaluated by a
classifier that predates it, so the model never saw the role list that
today's prompt carries on the reference host. The omissions in the baseline
were produced by a prompt with no role vocabulary block, and whatever the
experiment measures against today's prompt is a different comparison from the
one the baseline was drawn under.

## Why a replay, not a forward measurement

At snapshot time the reference host served `z-ai/glm-5.3-flash` through
OpenRouter. That model omitted `confidence` on 0 of 25 arcs, and the last
`confidence outside` line in the retained logs is dated 2026-09-30. A forward
measurement on the current model starts from about zero, and no prompt change
can show a drop from there. About six arcs a day reach the evaluator, so the
traffic to wait out a change is not there either.

Changing the host's model to bring the defect back is ruled out. An unplanned
host change already contaminated an earlier proof (see the note in
[Live tenant proof](live-tenant-proof.md)), and this experiment does not touch
the host's model, config, cron, plugin or markers.

So the experiment replays glm-5.2-era arcs through the deployed classifier and
the real `call_llm` inside Hermes' own environment, with only the model
pinned. It calls the evaluator and the validator and nothing that writes a
sidecar line, a marker or a ledger line, so the replay ships nothing and
backfills nothing. TRU-07's forward proof stays Phase 70's.

## Pre-registered protocol

This section was committed before the first replay call, and nothing in it
changes after a result is seen. Every number below is also a constant in
`tests/confidence_replay_harness.py`, and a test fails if the two disagree.

### Pool

An arc is eligible when all of these hold:

- its sidecar record has sequence 0, execution status SUCCESS and model
  exactly `z-ai/glm-5.2`;
- a `kind: job` marker for the same job has status SUCCESS;
- the production transcript reader returns a non-empty transcript for its
  session;
- no message in that session is later than the sidecar record's timestamp.

The last rule is the transcript-drift exclusion. A session that kept
receiving messages has a different transcript today than it had at evaluation
time, so replaying it would test a different input from the one that produced
the omission. Each exclusion is counted once, at the first rule that rejects
the arc. The census read the reference host's state read-only and made no
model call.

| Step | Arcs |
|------|-----:|
| Sidecar records read | 522 |
| Not sequence 0 | 0 |
| Duplicate of an arc already seen | 0 |
| Execution status not SUCCESS | 148 |
| Model not `z-ai/glm-5.2` | 46 |
| No SUCCESS job marker | 0 |
| Empty transcript | 0 |
| Transcript drift | 1 |
| **Eligible** | **327** |

The cap is 300. When more arcs are eligible, the 300 most recent by sidecar
timestamp are kept, so the pool is 300 arcs. If the operator picks the reduced
option at the spend checkpoint, the cap is 150, decided before any call and
applied the same way. Not every pool arc reaches the confidence check: an arc
that stops at the mechanism or the hours and rate gate is in the pool but not
in any rate's denominator.

The census also applied every arm to the host's real prompt for every pool
arc, built from the host's real configuration with its 173-entry rate card.
All seven arms applied cleanly. The mean A1 prompt is 10,582 characters.

### Arms

| Arm | What it changes | Hypothesis tested | Edits |
|-----|-----------------|-------------------|------:|
| A0 | The pre-PR-#140 prompt: the role list is removed by config, no text edit | The baseline was drawn under a prompt without the role list; A0 shows whether the harness reproduces that era | 0 |
| A1 | Today's prompt, unchanged | The deployed prompt, and the baseline every candidate is compared with | 0 |
| A2 | A1 repeated | The noise floor: how far two runs of the same prompt differ | 0 |
| B | Promote: `confidence` moves out of the orphan bullet after the role list into a line directly under the mechanism list, and the preamble now says those shared fields come with every mechanism | Declaration scope: the model reads the preamble's "only the fields under that mechanism's block" as excluding a field that sits under no block | 3 |
| C | Per-block: `confidence` is deleted from the trailer and repeated inside each of the three mechanism blocks | Proximity: the model supplies a field when it sits beside the other fields it is copying | 3 |
| D | B plus one sentence saying `confidence` is required and that a response without it is discarded in full | Wording: a stated consequence changes the model's behaviour | 4 |
| E | B plus a narrower abstention clause: the model is told not to invent hours or a rate, instead of not inventing "a number" | The abstention clause's "do not invent a number to fill the field" is read as covering `confidence` | 4 |

The exact strings are constants in `tests/confidence_replay_harness.py` at the
pre-registration commit. No arm carries an example value for any field, so no
arm can anchor the model on a number. Every arm keeps the paragraph that says
the transcript is data, not instructions, exactly once. Every edit asserts how
many times its anchor occurs in the instruction text and fails loudly on any
other count, so a drift in the deployed builder stops the run instead of
producing a wrong arm.

### Instrument

An omission is counted only when the production validator emits the log record
whose format string is
`revenium-classifier: rejected assessment, confidence outside [0,1]: %r`. That
is the string Phase 70 greps in `agent.log`. The harness matches the
unformatted format string by equality, never the rendered text, so model
output is never formatted.

The branch order mirrors production. After the served-model carrier is
removed, a response is classed in this order: invalid, timed out, null,
`newly_enabled_work`, and then the validator, which checks the mechanism, then
the hours and rate, then `confidence`. The denominator is the arcs that
reached the confidence check: the omitted ones plus the ones that passed it.
An arc that omitted is never dropped from it.

Per call the harness keeps only scalar diagnostics: whether the key was
absent, null, a string or another type; whether a differently spelled
confidence-like key was present; whether the word appears in the text outside
the object; the finish reason; the completion token count; the mechanism label;
and the served model. No response text is kept.

### Stages

One smoke call runs first, to confirm the harness reaches the model and the
served model is the pinned one. Stage 1 then runs A0, A1 and A2 on every pool
arc. Stage 2 runs B, C, D and E on every pool arc, and only when G0, G2 and G3
hold. The harness enforces this in code: it refuses the candidate stage
otherwise.

### Validity gate

- G0: the served model is `z-ai/glm-5.2` on at least 95% of the stage-1
  responses.
- G1: A0 reaches the check on at least 30 arcs and omits on at least 10% of
  them.
- G2: A1 and A2 differ in omissions by no more than max(3, a quarter of A1's
  omissions).
- G3: A1 reaches the check on at least 30 arcs and omits on at least 10% of
  them.

The harness is valid when G0 and G2 hold and either G1 or G3 holds. If it is
not valid, no arm verdict is read. Stage 2 needs G3, because a candidate can
only be shown to beat a prompt that reproduces the omission.

### Decision rule

A candidate arm clears against A1 only when all four hold:

- (a) its omission rate is at most half A1's;
- (b) a one-sided exact McNemar test on the arcs that reached the check in both
  arms gives p < 0.05;
- (c) it reaches the check on no fewer arcs than A1 did, less a tolerance of
  max(3, a tenth of A1's reached count);
- (d) its modal supplied confidence has a share of at most 80%, unless A1's
  modal share is above 80% too.

Criterion (d) exists so that an arm cannot win by teaching the model to emit a
constant. If more than one arm clears, the winner has the lowest omission rate,
then the fewest text edits, then the earliest in the order B, C, D, E.
Arithmetic at every cut is exact, in integers and fractions. No floating-point
number decides anything; the Wilson interval is for display only.

### Outcomes

The evaluator returns one of these, as a function of the data:

- `CLEARED — arm B`, `CLEARED — arm C`, `CLEARED — arm D` or
  `CLEARED — arm E`. The harness is valid, A1 reproduces the omission, and
  that arm clears all four criteria. SC1 and SC2 are met, with the mechanism
  explained from the arm that won. Only this outcome ships a prompt change in
  this phase.
- `CLEARED — arm A1, already deployed`. A1 does not reproduce the omission but
  A0 does, and A1 clears the same four criteria against A0. PR #140 already
  moved it, so the record explains the drop from the role list and ships
  nothing.
- `NOT CLEARED`. The harness is valid and no arm clears (or, when only A0
  reproduces the omission, A1 does not clear against A0). SC1 is met, because
  prompt changes were measured. SC2 is met by the plain statement that no
  prompt change tried moves the omission and why. Nothing ships.
- `NOT EVALUATED — harness did not reproduce the omission`. The gates fail, so
  no arm verdict is valid. The record states that the omission is not
  reproducible on demand and quotes the baseline on the current model. Nothing
  ships.
- `NOT RUN — spend declined`. No call was made. TRU-03 stays open, with the
  baseline and this protocol ready to run.

### Spend cap

The call cap is `7 × pool + 1 + ceil(7 × pool / 10)`: three gate arms and four
candidate arms for every pool arc, one smoke call, and a 10% headroom for the
single permitted retry of a transport error. The headroom is never for a
response that omitted `confidence`. That is an outcome, and it is not retried.

For the 300-arc pool the cap is 2,311 calls. Public prices for `z-ai/glm-5.2`
(input $0.152 per million tokens, output $12 per million tokens) with
deliberate overestimates (3 characters per token, the full 512-token output
cap on every call) give a ceiling of about $15.44. For a 150-arc pool the cap
is 1,156 calls and the ceiling about $7.72. Expected spend is lower, because
most responses stop short of the output cap. The ceiling is not an upper bound
if the provider bills hidden reasoning beyond the cap; the host sets a medium
reasoning effort, so this is a real possibility and is stated here rather than
assumed away.

The harness refuses to start a run that would exceed `--max-calls`, before its
first call. A retry is scheduled only within the budget that remains, at most
once per pair. A transport error that cannot be retried stands as a recorded
outcome.

### Side effects

The replay ships nothing to Revenium and writes nothing under the host's
Hermes home. It calls the evaluator and the validator and none of the code that
writes a sidecar line, a marker, a taxonomy entry or a ledger line. A fence
runs after the smoke call and after each stage, and the run stops on any hit.
It has four checks:

1. a new sidecar or marker line naming a pool job;
2. an appended line in the completion, jobs or tool-event ledger naming a pool
   session or job;
3. a change in the number of `state.db` rows whose model is `z-ai/glm-5.2`;
4. an appended `agent.log` line carrying the instrument text that has no
   session token, or a pool session's token.

The replay's spend lands on the host operator's provider account. Nothing in
the replay makes a metering call, so none of it appears in Revenium.

## Rejected alternatives

**Retry on omission.** Asking the model again when `confidence` is missing is
control flow, not a prompt change, and TRU-03 asks about the prompt contract.
It also changes the quantity measured: the per-arc outcome improves while the
per-call omission rate stays the same, so the log metric Phase 70 reads would
move for a reason that says nothing about the evaluator. It doubles the calls
for exactly the arcs that omit. And a retry prompt that says the field was
forgotten conditions the second answer on the omission, so the value is no
longer the model's answer to the original contract.

**`response_format` structured output.** It is not a prompt-level change. The
fields depend on the mechanism, so a schema would need a `oneOf`, and upstream
support for it varies by provider. It is the documented next step if no prompt
arm clears.

**Making `confidence` optional.** This is a contract change that needs a
decision, not an experiment. TRU-03 asks whether the evaluator can be made to
supply the field.

**Defaulting or inferring a value.** A default, or a value inferred from other
fields, is the silent workaround TRU-03 forbids. A missing `confidence` is
never filled in, so a number that looks like the model's judgement is never one
the code made up.

**Measuring forward on the current model.** The current model omitted on none
of the 25 arcs in the baseline, and no change can show a drop from about zero.

**Changing the host's model for the experiment.** An unplanned host change
already contaminated an earlier proof, and the experiment leaves the host's
model, configuration, cron and plugin alone.

**Backfilling or revaluing past jobs.** Metering is forward-only. A prompt
change affects arcs evaluated after it ships and never rewrites a job that was
already valued or left empty.

## The environment

- **Harness.** `tests/confidence_replay_harness.py`, sha256
  `b82270ef59ddd4aa71bbd822269ee8bdda072c233855c34a297842fd83e4d709`. The
  host's copy has the same digest, and the file is unchanged since the
  pre-registration commit `d333d20`, committed `2026-10-06T22:59:05-04:00`.
  Commits on the phase branch stay reachable through the phase PR after a
  squash merge.
- **Classifier under replay.** The deployed `classifier.py` has sha256
  `843e9f49fdf7a05dd2049d1e115e0723327b6c13ab483cb61a312a52ffb601b4`. The
  repo file at commit `ed1fa95` (PR #140) has that digest. The phase-start
  commit's file does not: it carries the later `reportModelEstimates` change,
  which the host has not deployed.
- **Model.** Pinned to `z-ai/glm-5.2` through provider `openrouter`. The smoke
  call observed the served model `z-ai/glm-5.2`.
- **Reasoning.** The host inherits `agent.reasoning_effort` of `medium`. The
  replay assumes `call_llm` applies it the same way here as it does inside the
  gateway (research assumption A2). Nothing in this record shows it does.
- **Call parameters.** Temperature 0.0, `max_tokens` 512
  (`_EVAL_MAX_TOKENS`), timeout 15.0 seconds (`_EVAL_TIMEOUT_SECONDS`).
- **Concurrency and runtime.** Concurrency 4, on the Python 3.11.15 interpreter
  from Hermes' own venv. The run started at `2026-10-07T15:14:42Z`.
- **Fence after the smoke call.** Exit 0, `fence: clean`. The smoke call made
  one recorded call, whose outcome passed the confidence gate.
- **Spend.** The calls ran on the host operator's provider account, after a
  human re-confirmed the spend at the point of spend.

## Results

Counts only. Everything below is transcribed from the report the harness
computed. The protocol was committed before the first call (`d333d20`,
`2026-10-06T22:59:05-04:00`), and the first call ran at
`2026-10-07T15:14:42Z`, the day after.

The replay made 901 calls: one smoke call and 900 stage-1 calls (A0, A1 and A2
on each of 300 arcs). Every response was served by `z-ai/glm-5.2`, and every
finish reason was `stop`. There were no transport errors and no retries. The
cap was 2,311 calls. Stage 2 did not run, for the reason given under
"Validity gate" below.

### Per arm

| Arm | Calls | Reached the check | Omitted | Omission rate (Wilson 95%) | Valued | Other outcomes |
|-----|------:|------------------:|--------:|---------------------------:|-------:|---------------:|
| A0 | 300 | 300 | 133 | 44.3% (38.8% to 50.0%) | 0 | 0 |
| A1 | 300 | 300 | 0 | 0.0% (0.0% to 1.3%) | 300 | 0 |
| A2 | 300 | 300 | 0 | 0.0% (0.0% to 1.3%) | 300 | 0 |

A0 shows 0 valued because its configuration removes the rate card. With no
card, the valuation step cannot value any arc, so the `Valued` column of the A0
row says nothing about the model. Its 167 arcs that passed the confidence check
are not valued by construction. "Other outcomes" counts invalid, timed-out,
null, newly-enabled-work, mechanism-rejected and hours-or-rate-rejected
responses. All three arms have none.

### Validity gate

| Gate | Holds | Reading |
|------|:-----:|---------|
| G0 | yes | The served model was `z-ai/glm-5.2` on every stage-1 response. |
| G1 | yes | A0 reached the check on 300 arcs and omitted on 133 (44.3%). |
| G2 | yes | A1 and A2 differ in omissions by 0, which is within max(3, a quarter of A1's omissions). |
| G3 | no | A1 reached the check on 300 arcs and omitted on 0, below the 10% needed. |

The harness is valid: G0 and G2 hold, and G1 holds. Stage 2 needs G3, because a
candidate arm can only be shown to beat a prompt that reproduces the omission.
A1 does not, so stage 2 was not eligible and no candidate arm (B, C, D or E)
was called. Running one anyway would have been a post-hoc analysis outside the
pre-registered protocol.

### Comparisons

| Comparison | b | c | Exact one-sided p | (a) at most half | (b) p < 0.05 | (c) reach | (d) calibration | Clears |
|------------|--:|--:|------------------:|:----------------:|:------------:|:---------:|:---------------:|:------:|
| A1 versus A0 (diagnostic) | 133 | 0 | 2^-133 (about 9.2e-41) | yes | yes | yes | yes | yes |
| B, C, D, E versus A1 | not run | not run | not run | not run | not run | not run | not run | not run |

Here b counts the arcs that omitted under A0 and reached the check cleanly
under A1, and c counts the arcs the other way round. The paired test covers all
300 arcs, because every arc reached the check under both arms.

### Diagnostics over omitted responses

The only omitted responses belong to A0 (A1 and A2 have none), so the table
covers 133 responses.

| Diagnostic | A0 (133 omitted) |
|------------|-----------------:|
| `confidence` key absent | 133 |
| Explicit null | 0 |
| Present but not a number | 0 |
| Differently spelled confidence-like key | 0 |
| The word `confidence` in the text outside the object | 1 |
| Finish reason `stop` | 133 |
| Median completion tokens | 329 |

### Calibration of the supplied confidence

| Arm | n | Distinct values | Modal share | Mean |
|-----|--:|----------------:|------------:|-----:|
| A0 | 167 | 7 | 137/167 (82.0%) | 0.690 |
| A1 | 300 | 7 | 181/300 (60.3%) | 0.661 |
| A2 | 300 | 6 | 190/300 (63.3%) | 0.669 |

### Fence and pre-registration

The side-effect fence exited 0 after the smoke call and after stage 1. It was
not needed after stage 2, which did not run. The directory names under the
host's plugin root matched the list taken at the census.

## The mechanism

**What the data isolates.** A0 and A1 differ by the approved-role block, which
the rate card's presence switches on: A0 is today's evaluator prompt with the
card removed from the configuration, so the block is absent (its mean prompt is
8,738 characters, against 10,582 for A1), and A1 is today's prompt as PR #140
deployed it. On the same 300 arcs, at temperature 0, A0 omitted
`confidence` on 133 and A1 on none. Not one arc went the other way (c is 0).
Two runs of A1 agree exactly (A2 also omits on 0), so the drop is not
run-to-run noise.

**The hypothesis, stated as one.** PR #140 added the role-list instruction. The
data show that the prompt which carries that instruction does not omit and the
prompt without it does. The data do not show which part of the change does the
work, because the replay has no arm that adds only part of the role block. Two
readings fit and neither is tested here. The first is that the role block
changes where the closing field list sits relative to the rest of the contract,
so the model reads `confidence` as part of the common fields. The second is that
naming a closed vocabulary for the role makes the model treat the response as a
structured record with every field to fill. Candidate arms B and C were built around
placement and D and E around wording, and none ran, because A1 gave them no
omission to beat.

**What the diagnostics show about the omissions.** In all 133 omitted A0
responses the `confidence` key was absent. It was never null, never a non-number
and never a renamed key, and every response finished normally (`stop`). So the
model dropped the field. It did not mangle it, hit the output cap, or put it
under another name. The median completion length of omitted responses (329
tokens) is close to that of A0 overall, so they are not short or truncated
answers. In one response the word appeared in the surrounding text, which is
too few to read anything into.

**Known Risk 1, checked for the winner and its baseline.** Under A1, 300 of 300
arcs passed the confidence check and all 300 were valued, so no arc that passed
the check then abstained on a role miss. That is consistent with what PR #140
set out to do: it constrains the role to the operator's list. A0 cannot be
compared on this, because its valued count is zero by construction (see the
note under the per-arm table). So the replay shows no role-miss abstention under
A1 on this pool, and says nothing about how many a host with a different card
or a different transcript mix would see.

**What changes.** Nothing ships. The deployed prompt is the one that cleared,
and no candidate arm was run. Plan 05's ship condition, a `CLEARED — arm`
outcome naming B, C, D or E, is not met.

## What this does not establish

- **One host and one replayed model.** The pool is 300 arcs from one reference
  host, all replayed through `z-ai/glm-5.2`. Nothing here says how another model
  behaves on this prompt.
- **A single temperature-0 pass per arm, plus A2.** Each arm was called once per
  arc. A2 is the only repeat, and it agrees exactly with A1 (0 and 0). That
  shows the replay is stable on this pool, not that every re-run would be.
- **Possible routing variance on OpenRouter.** The served model name matched on
  every response, but a provider behind the same name could still differ from
  the one that produced the original omissions.
- **Transcripts read today, not at evaluation time.** The one arc whose session
  kept receiving messages was excluded by the drift rule. A replay still reads
  the stored transcript as it is now, which can differ from what the evaluator
  saw.
- **The replay rate is not the log rate.** A0 omitted on 44.3% of its arcs. The
  baseline from the retained logs was 21.6% (22 of 102) for `z-ai/glm-5.2`.
  The populations differ (the replay pool is the 300 most recent eligible arcs
  and the logs cover only the later part of that model's era), and this record
  does not explain the gap. The comparison that matters, A1 against A0, is
  paired and does not depend on it.
- **The pool is one mechanism.** Every replayed response carried the same
  `economic_mechanism` label. The result says nothing about a response with a
  different mechanism, where the shape of the expected fields differs.
- **Not the forward proof.** TRU-07 is Phase 70's. This record shows a prompt
  that does not omit on replayed glm-5.2-era arcs, not that the reference host
  stops losing assessments to a missing `confidence`.
- **Nothing about the current model beyond its baseline count.** At snapshot time the
  host served `z-ai/glm-5.3-flash`, which omitted on 0 of 25 arcs in the retained logs. A
  zero there is where it started, and it cannot show a prompt change working.
- **Nothing about Job Value fill rate.** A job can pass the confidence check and
  still abstain on a role, and a replayed arc's `valued` flag is not what a
  deployed host's Job Value shows.
- **Nothing about the other agent that shares the tenant**, or about
  tenant-level aggregates.
- **The reasoning-inheritance assumption.** The host sets a medium reasoning
  effort, and the replay assumes `call_llm` applies it the same way in this
  process as the gateway does. If it does not, the replay measured a slightly
  different model configuration.

## For Phase 70

TRU-07 is a forward measurement on the reference host. This is a read-only
recipe for it. It writes nothing and calls nothing.

**Count three things per day.** From a stated UTC start (the day of the
deployment you are measuring from; no deployment comes out of this phase), count
the lines in `agent.log*` that contain each of these, and read the whole rotation
set oldest first:

- `rejected assessment, confidence outside [0,1]` (the instrument line: a
  confidence omission);
- `outcome evaluated job=` (a valued arc);
- `valuation implementation` (the role-miss and invalid-value lines).

For example, per file: `grep -c 'confidence outside \[0,1\]' agent.log*`,
then the same with each of the other two strings, tallied by the date stamp at
the start of each line.

**Slice by each line and never use Job Value fill rate.** Fill rate mixes two
causes. An arc rescued from the confidence gate can still abstain on a role the
card does not list, so the fill rate can stay flat while the omission count
falls. Each cause has its own line, and the instrument line is the one that
measures this requirement.

**On the current model, read zero as no-regression.** The host serves a model
that omitted on 0 of 25 arcs before any change. A zero count of the instrument
line is a report of "no regression", never of "improvement". A forward
measurement cannot show a drop from zero.

**If the host's configured model changes, re-run the experiment.** The harness
and the commands are unchanged. Run them with the Hermes venv's Python and an
`--out-dir` outside `~/.hermes` (for example `~/phase67-replay/run`), in this
order:

1. `confidence_replay_harness.py census --out-dir <dir> --hermes-home ~/.hermes`
2. `confidence_replay_harness.py fence --snapshot --out-dir <dir> --hermes-home ~/.hermes`,
   then record the run start with `date -u +%s`
3. `confidence_replay_harness.py smoke --out-dir <dir> --hermes-home ~/.hermes`
4. `confidence_replay_harness.py fence --check --since-epoch <start> --out-dir <dir> --hermes-home ~/.hermes`
5. `confidence_replay_harness.py run --stage gate --max-calls <cap> --concurrency 4 --out-dir <dir> --hermes-home ~/.hermes`
6. `confidence_replay_harness.py report --out-dir <dir> --hermes-home ~/.hermes`
7. `confidence_replay_harness.py run --stage candidates --max-calls <cap> --concurrency 4 --out-dir <dir> --hermes-home ~/.hermes`,
   only when the report says stage 2 is eligible, then `report` again
8. `confidence_replay_harness.py fence --check --since-epoch <start> --out-dir <dir> --hermes-home ~/.hermes`

`run` plans its retries before it makes any new call, so a transport error from
an invocation is retried by the next one. Run steps 5 and 7 a second time
before each `report`. The second invocation makes only the retries, within the
budget that remains, and a third makes no call.

Take the cap from the formula under "Spend cap", and ask the operator before
spending on their provider account. Delete the pool file (`pool.json`, the only
file that holds job names) from the run directory when finished.

**Metering is forward-only.** A change affects arcs evaluated after it ships.
Never re-ship or revalue past jobs.

## Harness amendments after the replay

The harness was amended after the recorded run, in response to review of
PR #149. The digest under "The environment" is the file that ran, and it stays
as written. The "Pre-registered protocol" section is unchanged, and a test now
pins its text. The amendments are in commits `30bdb28` and `0a4d7c0`.

The recorded verdict, `CLEARED — arm A1, already deployed`, and every number
in this record are unchanged. The checks below can refuse a result. None of
them can produce a winner.

**Report shows stage 2 eligibility.** `report` used to print one line,
`report: incomplete`, whenever any stage lacked a record. With stage 1 complete
and stage 2 eligible, it now prints one pass or fail line for each of G0 to G3
and names the next step: `run --stage candidates`, or "candidates incomplete"
when some candidate records exist. It still writes no `report.json` until the
protocol can be judged. The new output appears only in that state. The recorded
report had G3 = no, so it took the unchanged path.

**Replay inputs are pinned to the census.** Each pool entry now carries
`transcript_sha256`, the digest of the transcript the census read. `smoke` and
`run` re-read each arc's transcript before any call. If any digest differs, or
a pool has no digests, they print a count, make no call and exit `7`. The calls
then use the text that was checked, read once per arc per invocation. The
census also stops, with exit 5 and `timestamp_unit` `unreadable`, when
`state.db` cannot be opened or the timestamp query fails. Before, a failed read
passed as "no drift".

What the evidence supports is narrow. The recorded census reported
`timestamp_unit` `epoch_seconds`, so `state.db` opened and the query returned
stamps. The old harness read each transcript once per invocation and gave that
text to every arm in the invocation. The record cannot show, after the fact,
whether a pool session gained messages between the census and the run. The
900 stage-1 call timestamps form one continuous span of about 21 minutes with
no gap longer than 49 seconds. That is consistent with stage 1 running as one
invocation. It is not proof.

**Served model is checked per stage-2 arm.** When stage 2 is eligible, A1 and
each candidate arm must meet the 95% served-model share on its own. A1 is
checked because it is the base of every candidate comparison, and a pooled G0
can hold while one arm sits well below the share. Stage 2 never ran, so the
check never ran. The expected model is bound per out-dir in `run-model.json`,
which holds only the provider and model names. The first `smoke` or `run` that
makes calls writes it. Later invocations read it back, and a conflicting
`--model` or `--provider` exits 2 with no call. With no `--model`, the model
resolves to `z-ai/glm-5.2`, the model the environment section records, so G0
compared against the same model as before. These checks extend G0 past the
pre-registered text.

**The budget counts unfinished calls.** `run` writes a reservation to
`attempts.jsonl` in the run directory before each model call, and a done line
once that call's record is saved. A process killed mid-chunk leaves calls that
may have been billed but have no record. On resume each unfinished reservation
counts as spent against `--max-calls`, so those calls are not repeated for
free. Each saved record carries the id of its reservation, and a reservation
whose id is on a saved record is finished. A crash between saving the record
and writing the done line therefore counts that call once. The file holds only
an arm, a stage label, the pseudonymous arc key and a random id. `report` and
the gates never read it, and they ignore the `reservation` field on a record.
Records saved without the field still parse. A run directory with no
`attempts.jsonl` budgets as before.

**The evaluator config and classifier are bound to the run.** The first `smoke`
or `run` that makes calls writes `run-inputs.json`, which holds a digest of the
evaluator config, a digest of `classifier.py` and the evaluator version, and no
config text. A later `smoke` or `run` whose config or classifier differs prints
which one changed, makes no call and exits `7`. `report` does not check it. A
run directory with no `run-inputs.json` binds on its next call that makes calls.

**Operator notes for a re-run.** A `pool.json` written before this amendment is
refused with exit `7`, so run `census` into a fresh `--out-dir`. Exit `7` after
a fresh census means a pool session changed since the census. Start over in a
fresh out-dir. A re-census into the same dir would leave records for arcs
outside the new pool. The first `smoke` or `run` binds the provider and model,
and later invocations read them back.
