# A read-surface ask for the Revenium API team

[← Back to the project README](../README.md)

This repo-only page records a standing request for the owners of `revenium jobs
roi`'s output shape. It is not part of the skill bundle and is unavailable on a
tap-installed host. A companion page, [`docs/cli-verb-ask.md`](cli-verb-ask.md), requests verbs and flags that do not exist at all — this page requests fields on a display verb that already does.

## What is true today

A live verification against a real Revenium tenant, recorded in
[`docs/claim-distinctions-and-evidence-boundaries.md`](claim-distinctions-and-evidence-boundaries.md#the-product-truth-boundary),
found that `revenium jobs roi <id>` surfaces no `evidence_class`, no
`evaluator`, and no `confidence` — in either its JSON or its table output.
Only the separate `jobs outcome-history` command echoes that metadata blob at
all. This finding is dated 2026-08-31, at the Phase 53 plan gate.

**Re-verified 2026-09-03, live, during Phase 56's induced-probe arm
(`docs/comprehensive-roi-proof.md`, "D-06 — the read-surface finding,
re-verified and re-dated").** Both fields remain absent from `jobs roi`, in
both JSON and table output, on two fresh tenant rows read that day. No change
on Revenium's side has occurred between the two dates.

`jobs roi` works as designed, but its display surface lacks provenance.

The surface renders a model estimate and a customer-configured figure with the
same visual weight. From that screen alone, a reader cannot tell which kind of
number is shown.

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

**Re-verified 2026-09-03, live, during Phase 56's induced-probe arm**
(`docs/comprehensive-roi-proof.md`, "Toggle comparison (D-05) and the matched
disabled-arm job") **— the boundary still holds, unchanged.** A fresh
withheld row (`flatten_nested_list_python_function_23b5`) rendered
`Outcome Value $0.00` / `ROI % 0.00%` in the table form while its JSON form
correctly returned `"outcomeValue": null` and `"roi": null` for the same
job — the identical gap, on a different row, two days later.

This compounds the first gap. Even a reader who notices the missing
`evidence_class` cannot use the table to distinguish "withheld by policy" from
"priced at zero." Only the JSON form preserves that distinction today.

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

The gate is a limit imposed by this skill, not by Revenium. If the surface
changes, the gate can widen. This request is not a Revenium commitment or an
agreed roadmap item.

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

Both `jobs roi` outputs, **JSON and table**, need these fields. A JSON-only
change would leave the table view opaque.

Separately from the provenance fields above: the **table** renderer should
distinguish a withheld/`null` `outcomeValue` (and the `roi` derived from it)
from a genuinely measured zero, the way the JSON renderer already does. This
does not require a new field — the JSON output already carries the correct
`null` — only that the table formatter stop coercing `null` to `"$0.00"` /
`"0.00%"` before display.

## What it would unlock

If `jobs roi` carried `evidence_class`, the Phase 53 gate could widen: an
estimate could ship with its label visible where readers encounter it.
Widening the gate would remain a separate decision after verifying that the
field renders. This is a possibility, not a plan or timeline.

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

## Where the re-verification evidence lives

Both findings on this page were re-verified live on 2026-09-03, alongside
Phase 56's comprehensive ROI proof. The full captures — both `jobs roi`
forms, both jobs, and the point read-back that shows the same fields present
in `jobs outcome-history` — are in
[`docs/comprehensive-roi-proof.md`](comprehensive-roi-proof.md), sections
"D-06 — the read-surface finding, re-verified and re-dated" and "Toggle
comparison (D-05) and the matched disabled-arm job."
