# A read-surface ask for the Revenium API team

[← Back to the project README](../README.md)

This page is repo-only — it is not part of the skill bundle and a tap-installed
host never sees it. It is a standing, tracked ask addressed to the people who
own `revenium jobs roi`'s output shape, not a note buried inside a document
about something else.

## What is true today

A live verification against a real Revenium tenant, recorded in
[`docs/claim-distinctions-and-evidence-boundaries.md`](claim-distinctions-and-evidence-boundaries.md#the-product-truth-boundary),
found that `revenium jobs roi <id>` surfaces no `evidence_class`, no
`evaluator`, and no `confidence` — in either its JSON or its table output.
Only the separate `jobs outcome-history` command echoes that metadata blob at
all. This finding is dated 2026-08-31, at the Phase 53 plan gate, and has not
been re-verified since.

`jobs roi` is not broken. It carries no provenance because none was designed
into it — this is a gap in a display surface, not a defect in a working
feature.

The consequence: a model-estimated figure and a figure a customer configured
are rendered with the exact same visual weight on that surface. A reader
looking at `jobs roi` has no way to tell, from that screen alone, which kind
of number they are looking at.

## A second, distinct gap: a withheld value renders identically to a measured zero

A second finding, independent of the missing-provenance gap above, surfaced
2026-09-01 during Phase 53's live-tenant arm
(`.planning/phases/53-value-on-the-wire/53-03-SUMMARY.md`, gitignored — this
page is the durable record) and is repeated here so it does not depend on a
planning artifact that can vanish.

`revenium jobs roi <id>`'s **table** output renders a withheld/`null`
`outcomeValue` as `"$0.00"`, and the derived `roi` field as `"0.00%"` —
visually indistinguishable from a job that was genuinely measured and found
to be worth exactly nothing. The **JSON** output does not have this problem:
it correctly returns `"outcomeValue": null` and `"roi": null` for the same
withheld record. This was observed against
`implement_p53_ctrl_gcd_function_8404`, a real tenant row whose value the
Phase 53 evidence-class gate correctly withheld (its `evidence_class` is
the forced `MODEL_ESTIMATED_DEMO` constant — see "What this skill did about
it" below).

This compounds the first gap rather than duplicating it: even a reader who
already knows to distrust a `jobs roi` figure with no `evidence_class` has
no way, from the table alone, to tell "withheld by policy" apart from "priced
at zero." Only the JSON form preserves that distinction today.

## What this skill did about it, instead of waiting

Rather than hold value reporting off until a server-side change lands, Phase
53 gated the skill's own reporting at the wire. The reportable evidence-class
allow-list is a code constant — five members, derived by subtraction from the
six declarable evidence classes minus the one label whose basis is a model
and nothing else: `ACTIVITY_MEASURED`, `OUTPUT_OBSERVED`, `OUTCOME_OBSERVED`,
`CUSTOMER_CONFIGURED`, `CUSTOMER_CONFIRMED`. `MODEL_ESTIMATED_DEMO` is
deliberately refused — not because it ranks lower than the other five (EGV-10
forbids treating these nine labels as a confidence ladder), but because it is
the one label whose entire basis is a model's own output, and the one surface
that would display it cannot say so.

That gate is enforced at two independent points — the classifier, which
refuses to mark a model-estimated record `reportable` in the first place, and
the reporter, which re-checks the class before a value family ever reaches
`--metadata`. Neither site trusts the other; a record has to clear both.

This ask is the other half of that same decision, honestly stated: the gate
above is a limit this skill imposed on itself, not a limit Revenium imposed
on us. If the surface below changes, our gate can widen. Nothing about that
depends on this ask being granted, and nothing here should be read as a
commitment on Revenium's part — it is a request, not an agreed roadmap item.

## The concrete ask

For `revenium jobs roi <id>` to let a reader distinguish a measurement from an
estimate, at minimum it would need to surface:

- **`evidence_class`** — the single field that names what kind of claim a
  value is. Without this, no other change below matters; a reader still can't
  tell an estimate from a measurement.

And to match what `jobs outcome-history` already returns for the same job:

- **`evaluator`** — which evaluator (or boundary implementation) produced the
  record.
- **`confidence`** — the evaluator's own stated confidence in its output,
  where one exists.

Both outputs `jobs roi` currently produces — **JSON and table** — would need
to carry these fields. A fix that lands only in JSON leaves the table view,
which is what most people actually look at, exactly as opaque as it is today.

Separately from the provenance fields above: the **table** renderer should
distinguish a withheld/`null` `outcomeValue` (and the `roi` derived from it)
from a genuinely measured zero, the way the JSON renderer already does. This
does not require a new field — the JSON output already carries the correct
`null` — only that the table formatter stop coercing `null` to `"$0.00"` /
`"0.00%"` before display.

## What it would unlock

If `jobs roi` carried `evidence_class`, the Phase 53 gate described above
could widen without changing the reasoning behind it: an estimate could ship
labelled as an estimate, at the place where it is read, rather than being
withheld because the place it would be read cannot say what it is. This is
stated as what becomes *possible*, not as a plan or a timeline — widening the
gate would still be a separate, deliberate decision, made against a rendered
field this skill could then verify actually appears.

## What is NOT being asked

- **No change to how values are stored.** The record shape, the sidecar, and
  the wire payload this skill sends are unaffected by this ask.
- **No new verb.** This is a request to add fields to an existing display
  surface (`jobs roi`), not to add a new CLI command or API endpoint.
- **No change to `jobs outcome-history`.** That surface already carries this
  metadata and is not part of this ask.

## Why this is a read-surface question, not an ingestion one

The data already reaches Revenium today. Every reportable record this skill
ships carries `evidence_class`, `evaluator`, and `confidence` (where present)
in its `--metadata` payload, and `jobs outcome-history` already echoes them
back. The gap is entirely on the `jobs roi` display path — the data exists
server-side and is retrievable through one command; it simply isn't rendered
by the other.
