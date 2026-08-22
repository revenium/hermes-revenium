# Auxiliary Usage Sizing — Why Auxiliary Metering Was Not Built

## Verdict

Per the pre-committed rule: at or above 1% of fleet cost share, the reporter
change gets written; below 1%, the phase closes unbuilt and the
`post_api_request` re-architecture (spike P-D) is promoted into its slot. The
rule was fixed in advance of seeing the number, so the verdict below is
falsifiable rather than rationalized.

Measured, fleet-wide, across all ten metered profiles' whole retained
session history:

- **Auxiliary cost share: 0.4598%** — the number the gate decides on.
- **Auxiliary token share: 0.1042%** — reported alongside cost, not used to
  decide, because compression is cache-heavy and the two diverge sharply.

**Outcome: the gate failed. The phase closes unbuilt. No runtime file was
changed.**

Date: 2026-08-15.

## Why this document exists

The planning directory that captured this measurement is excluded from
version control, so this file is the committed mirror of the headline
findings and the replayable method. Deleting it turns the repository's own
test suite red, which is the whole point: a verdict that only exists in an
untracked directory is a verdict that did not happen.

## What was measured

Population and method: all ten metered profiles on the production fleet
host, across each profile's whole retained session database, aggregated.
Every read was a read-only `sqlite3` `SELECT` statement; nothing was written
to any session database.

The ten profiles: gtm, marketing, devops, qa, coder, playtester, cfo, pm,
community, lorekeeper. These are generic role labels, not identifying
information, and the per-profile reading below depends on naming them.

The denominator is the same `sessions` population the reporter already ships
today, filtered on non-zero input or output tokens — "total" here means the
same thing it means in Revenium today.

## Results

### Fleet totals

| Metric | Value |
|---|---|
| Total cost | $137.62116203 |
| Total tokens | 962,643,980 |
| Auxiliary cost | $0.63284979 |
| Auxiliary tokens | 1,003,215 |
| Cost share | 0.4598% |
| Token share | 0.1042% |

### Per profile

| Profile | Total cost | Total tokens | Aux cost | Aux tokens | Cost share | Token share |
|---|---|---|---|---|---|---|
| gtm | $2.72487464 | 13,774,543 | $0.0011642 | 18,108 | 0.0427% | 0.1315% |
| marketing | $5.22288036 | 54,576,943 | $0.0026614 | 100,795 | 0.0510% | 0.1847% |
| devops | $25.10663582 | 105,149,864 | $0.0062368 | 4,716 | 0.0248% | 0.0045% |
| qa | $2.19408498 | 32,487,239 | $0.0071946 | 4,038 | 0.3279% | 0.0124% |
| coder | $92.69080557 | 718,372,050 | $0.49889751 | 754,425 | 0.5382% | 0.1050% |
| playtester | $0.0263568 | 228,097 | $0.0005462 | 208 | 2.0723% | 0.0912% |
| cfo | $3.66118632 | 12,648,602 | $0.11215606 | 67,275 | 3.0634% | 0.5319% |
| pm | $3.74441662 | 17,482,573 | $0.0036444 | 12,195 | 0.0973% | 0.0698% |
| community | $0.0 | 35,347 | $0.0 | 754 | 0.0000% | 2.1331% |
| lorekeeper | $2.24992092 | 7,888,722 | $0.0003486 | 40,701 | 0.0155% | 0.5159% |
| **FLEET TOTAL** | **$137.62116203** | **962,643,980** | **$0.63284979** | **1,003,215** | **0.4598%** | **0.1042%** |

Reading: only `cfo` (3.0634%) and `playtester` (2.0723%) cross the 1%
threshold, and both sit on near-zero denominators ($3.66118632 and
$0.0263568 of total spend respectively) where a handful of `approval` calls
dominate. Neither is representative of the fleet.

### Per native task

| Task | Rows | Tokens | Cost |
|---|---|---|---|
| `` (empty string — main-loop mirror, not auxiliary) | 2,650 | 962,643,980 | $137.62116203 |
| `approval` | 82 | 387,134 | $0.60646967 |
| `title_generation` | 57 | 41,302 | $0.02638012 |
| `compression` | 16 | 574,779 | $0.00000000 |

`approval` is 95.83% of auxiliary cost. `compression` is 57.29% of auxiliary
tokens while contributing zero cost — the token/cost divergence the gate
rule anticipated by deciding on cost while still reporting tokens.

## Corrections to the `session_model_usage` characterization

This is the highest-value durable content in this document — findings with
their evidence, not assertions.

### 1. It is not an auxiliary-only table

The empty-`task` bucket is the main-loop mirror, not a separate auxiliary
signal. Its summed tokens and cost equal the `sessions` table's totals to
the cent, on every profile. Worked example, the devops profile: `sessions`
totals **105,149,864 tokens / $25.10663582**; `session_model_usage` filtered
to `task=''` totals the identical **105,149,864 tokens / $25.10663582**.

The consequence, stated in the strongest terms available: any future reader
that queries this table without filtering to non-empty `task` will re-ship
every already-metered main-loop token, roughly doubling reported spend and
inflating every guardrail counter to match. The tell: a sizing measurement
that comes back near 100% cost share means the filter was omitted — the true
figure is 0.4598%.

The upstream pull request's claim that auxiliary writes happen "without
touching the `sessions` summary counters" is literally true — no `sessions`
row is mutated — but functionally misleading for anyone sizing or metering
auxiliary usage from this table: the *content* of the empty-`task` bucket
duplicates what `sessions` already reports.

### 2. The primary key is six-dimensional, not four

The roadmap's description assumed a four-field identity of session, model,
provider, and task. The live table's actual primary key is: session id,
model, billing provider, billing base URL, billing mode, and task — six
fields, not four.

Live proof: one session on the coder profile carries two distinct rows for
an identical session/model/task tuple, differing only in billing provider
and billing base URL, because API routing changed mid-session for the same
model and task. (The session id itself is deliberately not transcribed
here.)

Consequence: a four-field key would treat those two rows as one, corrupting
delta arithmetic on whichever reports second.

### 3. The real native task vocabulary is three values, not five

Observed fleet-wide, across all ten profiles' whole retained history:
`title_generation`, `approval`, `compression`. The values `vision`,
`web_extract`, and `session_search` — three of the five originally assumed —
have zero rows, ever, on this fleet. `approval` was not anticipated at all,
and it is the dominant auxiliary cost contributor.

Also worth recording: `actual_cost_usd` is 0.0 on every row, on all ten
profiles. `estimated_cost_usd` is the only populated cost signal, and
nothing is being lost by continuing to ship it.

## Reproducing this measurement

The non-empty-`task` filter on the second and third queries below is the
load-bearing clause — see correction 1 above. Omitting it re-ships every
main-loop token as if it were auxiliary spend.

```sql
-- Per profile, run against each profile's own retained session database.
-- "Total" = the same `sessions` totals the reporter already ships today.
SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total_cost,
       COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens), 0) AS total_tokens
FROM sessions
WHERE input_tokens > 0 OR output_tokens > 0;

-- Auxiliary aggregate — the non-empty-task filter is load-bearing:
SELECT COALESCE(SUM(estimated_cost_usd), 0) AS aux_cost,
       COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens), 0) AS aux_tokens
FROM session_model_usage
WHERE task != '';

-- Per-native-task breakdown:
SELECT task, COUNT(*) AS rows, SUM(input_tokens+output_tokens+cache_read_tokens+cache_write_tokens) AS tokens,
       SUM(estimated_cost_usd) AS cost
FROM session_model_usage
WHERE task != ''
GROUP BY task;
```

These three queries run per profile, against that profile's own session
database, and the ten profiles' results are summed to produce the fleet
totals above.

## Other live observations worth preserving

- Model names can contain a literal colon (an OpenRouter free-tier naming
  convention) — a field-shifting hazard for any colon-delimited ledger line
  built from this table.
- `actual_cost_usd` is uniformly zero across every row, on every profile.
- A billing provider value of `auto` paired with a real base URL is common
  on auxiliary rows and is not one of the values the reporter's existing
  provider-inference logic special-cases, so it would pass through literally.
- The table's session id is a cascading foreign key onto `sessions`, with
  zero orphans and zero foreign-key violations observed.

## What this means for a future auxiliary-metering phase

The design work was completed and is preserved: a ledger-key shape, a
taxonomy design, an attribution-parity requirement, and a deploy sequence
all exist in this phase's own planning artifacts, so a future phase restarts
from a design, not from zero. Two things a future phase must carry forward
from this document regardless of anything else: the non-empty-`task`
filter, and the six-column identity.

The gate is re-runnable from the SQL above, and the verdict recorded here is
a measurement, not a policy — if fleet traffic composition changes
materially, re-running the gate is a read-only exercise.

## Independent confirmation

Re-derived 2026-08-15: connected to the production fleet host read-only and
ran the three queries above, verbatim, against each of the ten profiles' own
session databases, then summed the results. Only `SELECT` statements were
issued; nothing was written to any session database.

**Cost share: 0.4598%** (unchanged from the gate read, still below the 1%
threshold).

| Metric | Original gate read | Independent re-derivation |
|---|---|---|
| Cost share | 0.4598% | 0.4598% |
| Total cost | $137.62116203 | $137.62116203 |
| Total tokens | 962,643,980 | 962,643,980 |
| Auxiliary cost | $0.63284979 | $0.63284978 |
| Auxiliary tokens | 1,003,215 | 1,003,215 |

Consistent with the recorded gate measurement — the auxiliary-cost figure
differs from the original by $0.00000001, a floating-point summation-order
artifact of aggregating ten profiles' `REAL` columns in a different order,
not a change in underlying data. Still well below the 1% threshold. The
0.4598% gate figure above is the decision of record and is left unchanged.

## Verified against

Date: 2026-08-15. Method: read-only SQL against ten metered profiles on a
production fleet host running an out-of-tree cron wrapper. Host addresses,
credential filenames, remote login strings, and individual session
identifiers are deliberately omitted and live only in this repository's
local, excluded evidence artifact. Profile role labels and aggregate spend
figures are retained because the per-profile reading above depends on them.
