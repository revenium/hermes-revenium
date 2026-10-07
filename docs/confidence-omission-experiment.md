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
this phase's. It belongs to Phase 70 and runs after deployment. As of this
commit, nothing under `skills/` has changed: this record and the tests that
guard the code it must not touch are the only additions.

## Verdict, up front — every criterion, in one table

| # | Criterion | Source | Verdict |
|---|-----------|--------|---------|
| 1 | At least one prompt-level change to the evaluator contract is tried and measured against the omission-rate baseline below | TRU-03 / SC1 | PENDING — not yet measured |
| 2 | Either the omission rate measurably drops and the mechanism is explained here, or this record states plainly that no prompt change tried moves it, and why | TRU-03 / SC2 | PENDING — not yet measured |
| 3 | No change to `LABEL_RE`, `TRIVIAL_BLOCKLIST`, the reportability gate or evidence-class promotion | SC3 | PENDING — not yet measured |

**TRU-03 status:** baseline preserved; the experiment itself has not run.

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
