# Wire contract audit — Revenium Platform API 2.20.0-SNAPSHOT

[← Back to the docs index](README.md)

This page records the Phase 57 (SSE-02) result of checking every request this
skill emits against the `2.20.0-SNAPSHOT` platform API spec, field by field.
It is a repo-only page, not part of the skill bundle, and is unavailable on a
tap-installed host. It changes no shipped runtime behaviour and implements
nothing. It owns neither the CLI's own flag semantics nor the server's
schemas — it only records how the two line up today.

## Scope

Coverage is the roadmap's eight verbs (D-10): `jobs create`, `jobs outcome`,
`jobs outcome-update`, `meter completion`, `meter tool-event`,
`guardrails enforcement-rules get`, `guardrails budget-rules list`, and
`guardrails enforcement-events list`.

The spec under comparison is `.planning/research/revenium-oas-v2.20.0-SNAPSHOT.json`
(and its formatted twin, `revenium-oas-v2.20.0-SNAPSHOT.pretty.json`) —
`openapi: 3.1.0`, `info.version: "2.20.0-SNAPSHOT"`, **219 paths**, **442
schemas** (all four figures re-confirmed this session by direct `json.load`,
not restated from an earlier document). The spec file itself is **gitignored**
and therefore not re-checkable from a fresh clone. The reproducible bridge is
`tests/extract_operation_type_enum.py` (Phase 57 Plan 01, D-04/D-06), a
committed, operator-run extractor that walks the spec's `operationType` enum
directly and writes a provenance-carrying extract; the extract's own JSON
pointers are the closest thing to a re-checkable spec path this repo carries
across a fresh clone.

Every `revenium` CLI `--help` claim in this document was captured on **this
development machine**, `revenium 1.5.0 (0f5f3a7)` — upgraded from the stale
`1.4.0` this same machine carried at research time via
`brew upgrade revenium`, immediately before this audit was written, matching
the confirmed field version (`docs/comprehensive-roi-proof.md:63,482` records
the multiplex VM at the same `1.5.0 (0f5f3a7)`). One correction to the plan's
assumed invocation: `revenium --version` errors (`unknown flag: --version`);
the correct command is `revenium version`, which is what was actually run.

Audit date: 2026-09-03.

## How to read a verdict

Every audited request carries exactly one of three verdicts:

- **compatible** — an OAS path and a request/response schema are cited, and
  the flags this skill sends line up with that schema's fields (type, enum
  membership, required-ness checked).
- **discrepancy** — named, with evidence: the skill sends something the
  schema does not accept, or omits something the schema requires.
- **unverifiable** — the spec does not cover this surface. The reason is
  stated plainly, together with what would be needed to verify it.

**Unverifiable is a first-class outcome, not a partial or lesser one.** A
request with no schema to check against still gets a row; it is never
omitted for lacking one (D-09).

## The one hop this audit does not control

This skill emits CLI flags, not HTTP request bodies. The `revenium` CLI is
the one hop between what this skill sends and what actually crosses the wire,
and this skill does not control the CLI's own flag-to-field mapping — every
flag-to-schema-field mapping below is therefore an inference, not a direct
observation of bytes on the wire. Three evidence classes are used, and are
named per row below:

- **schema-cited** — the flag's destination field is named directly in the
  OAS requestBody or response schema for the path this verb calls.
- **CLI help, observed at the stated version** — the flag's existence,
  description, and required-ness are read from `revenium <verb> --help` on
  the version named in `## Scope`, above.
- **assumption, with inference chain** — the mapping rests on corroborating
  detail (a shared example value, a matching description) rather than a
  literal name match between the CLI verb and the OAS path or schema.

A mapping supported only by the third class never yields a *compatible*
verdict. It yields *unverifiable*, carrying the named assumption and its
inference chain.

## Per-verb audit

### `jobs create`

- **Invocation site:** `skills/revenium/scripts/hermes-report.sh:3053-3080`
  (the `jobs_cmd` array), one of two `jobs create` call sites in this file —
  the other, an earlier precheck at line ~2155, builds the same shape and is
  not separately audited here since both use the identical flag set.
- **OAS path:** `POST /v2/api/jobs`
- **Request schema:** `JobResource`
- **Flag-by-flag mapping:**

  | CLI flag | Schema field | Type | Required | Evidence class |
  |---|---|---|---|---|
  | `--agentic-job-id` | `agenticJobId` | `string` | yes (`agenticJobId` in schema's `required` list) | schema-cited |
  | `--name` | `name` | `string, nullable` | no | schema-cited |
  | `--type` | `type` | `string, nullable` | no | schema-cited |
  | `--environment` | `environment` | `string, nullable` | no | schema-cited |
  | `--team-id` | (not a `JobResource` field — routing parameter, not a request-body field) | — | — | CLI help, observed at 1.5.0 |
  | `--organization-name` | (no corresponding `JobResource` property in this schema at all) | — | — | schema-cited (absence confirmed by direct enumeration of all 24 `JobResource` properties) |

  `--version` also exists on the CLI (`Job version identifier`) but this
  skill never sends it.

- **Verdict:** **compatible**, carrying the named spec-quality caveat below.
  `--organization-name` is sent by this skill's `jobs_cmd` build (BUG-2, so a
  job and its transactions never land in different orgs) but has no matching
  property anywhere in `JobResource`'s 24 properties — worth flagging plainly
  rather than silently assuming it lands somewhere unnamed; corroborating
  evidence that `organizationName` is accepted as a query-scoping/session
  parameter rather than a stored resource field would need a live capture,
  which this audit does not have. This rides as a caveat on this row's own
  verdict (stated once, below) rather than a separately-named finding, since
  the flag causes no known rejection (`docs/comprehensive-roi-proof.md`'s
  live captures show `jobs create` succeeding with `--organization-name`
  present).

  **Second caveat on this row — the unsent required fields.** `JobResource`'s
  `required` list carries **eight** entries, not one:
  `agenticJobId`, `entityVersion`, `hasOutcome`, `id`, `label`,
  `outcomeUpdateCount`, `resourceType`, `source`. This skill sends exactly one
  of them, `agenticJobId`. The mapping table above is accurate as far as it
  goes — `agenticJobId` genuinely is in the `required` list — but read against
  the schema alone, this skill's `jobs create` body omits seven required
  fields, and a *compatible* verdict has to say why that is not a defect
  rather than pass over it.

  It is not a defect, and the reason is empirical rather than schema-derived:
  `docs/comprehensive-roi-proof.md`'s live captures show `jobs create`
  succeeding with only `agenticJobId` present, so the server does not enforce
  the other seven on create. The likely explanation is that `JobResource` is
  the platform's single job **resource** schema, reused verbatim as this
  path's declared `requestBody` while its `required` list describes a
  *materialised* job — `id`, `entityVersion`, `resourceType`,
  `outcomeUpdateCount` and `hasOutcome` are all server-assigned, and cannot
  meaningfully be required of a create request. `JobResource_Read` is the 201
  response schema, which is consistent with that reading.

  Stated plainly so the verdict rests on named evidence: this row's
  *compatible* is **schema-cited for the four fields the skill sends, and
  live-capture-cited for the seven it does not.** That is a weaker basis than
  the other four compatible verdicts in this document, all of which are
  schema-cited throughout. If the ingest service ever begins enforcing
  `JobResource.required` literally, this is the row that breaks first.

### `jobs outcome`

- **Invocation site:** `skills/revenium/scripts/hermes-report.sh:4242-4300`
  (the `outcome_cmd` array).
- **OAS path:** `POST /v2/api/jobs/{agenticJobId}/outcome`
- **Request schema:** `ReportOutcomeRequest_Read`
- **Flag-by-flag mapping:**

  | CLI flag | Schema field | Type | Enum | Required | Evidence class |
  |---|---|---|---|---|---|
  | `--result` | `executionStatus` | `string` | `[SUCCESS, FAILED, CANCELLED]` | yes (schema's sole required field) | schema-cited — note the CLI flag name (`--result`) and the wire field name (`executionStatus`) diverge; `--help`'s own description ("Execution result: SUCCESS, FAILED, or CANCELLED") is what ties them together, not a literal name match |
  | `--outcome-type` | `outcomeType` | `string, nullable` | `[CONVERTED, ESCALATED, DEFLECTED, UNSUCCESSFUL, CUSTOM]` | no | schema-cited — this skill only ever sends the literal `CONVERTED`, a member |
  | `--outcome-value` | `outcomeValue` | `number, nullable` | — | no | schema-cited |
  | `--outcome-currency` | `outcomeCurrency` | `string, nullable` | `[USD, EUR, CAD, GBP, JPY, CNY, MXN, COP, ARS, ZMW, AUD, ZWG]` | no | schema-cited — this skill only ever sends `USD`, a member |
  | `--metadata` | `metadata` | `string, nullable` | — | no | schema-cited |
  | `--team-id` | (routing parameter, not a `ReportOutcomeRequest_Read` field) | — | — | — | CLI help, observed at 1.5.0 |

- **Verdict:** **compatible.**

### `jobs outcome-update`

- **Invocation site:** `skills/revenium/scripts/correct-assessment.sh:940-950`
  (the `outcome_update_cmd` array). Operator-only, never invoked from cron.
- **OAS path:** `PATCH /v2/api/jobs/{agenticJobId}/outcome`
- **Request schema:** `UpdateOutcomeRequest_Read`
- **Flag-by-flag mapping:**

  | CLI flag | Schema field | Type | Enum | Required | Evidence class |
  |---|---|---|---|---|---|
  | `--reason` | `reason` | `string, nullable` | — | required by the CLI's own `--help` ("(required)"); the schema itself marks no field required | schema-cited + CLI help — `correct-assessment.sh` always sends it |
  | `--outcome-value` | `outcomeValue` | `number, nullable` | — | no | schema-cited, sent conditionally (only alongside `--outcome-currency`) |
  | `--outcome-currency` | `outcomeCurrency` | `string, nullable` | `[USD, EUR, CAD, GBP, JPY, CNY, MXN, COP, ARS, ZMW, AUD, ZWG]` | no | schema-cited |
  | `--metadata` | `metadata` | `string, nullable` | — | no | schema-cited |
  | `--team-id` | (routing parameter, not an `UpdateOutcomeRequest_Read` field) | — | — | — | CLI help, observed at 1.5.0 |

  `expectedEntityVersion` (`integer, nullable`) is present in the schema but
  is confirmed **absent from the CLI's own `--help` at 1.5.0** — re-verified
  this session, not merely restated from research done against the stale
  `1.4.0` local install. It is present-and-unusable through this skill's one
  interface (the CLI), forward-relevant to Phase 59 / SSE-05, and explicitly
  out of scope to adopt here.

- **Verdict:** **compatible.**

### `meter completion`

- **Invocation sites:** three within `hermes-report.sh` — the auxiliary pass
  (`hermes-report.sh:1227-1248`), the marker path
  (`hermes-report.sh:3236-3257`), and the zero-marker fallthrough
  (`hermes-report.sh:3394-3423`) — plus the event path in
  `skills/revenium/scripts/api-event-report.sh` (its own `meter completion`
  call, not separately re-audited here as a fourth verb since it is the same
  ingest surface).
- **OAS path:** **none among the 219.** This is the platform API spec; the
  metering **ingest** surface it does not cover. Exhaustive enumeration of
  every one of the 219 paths this session found only read-back surfaces —
  `GET /v2/api/sources/metrics/ai/completions`,
  `GET /v2/api/sources/metrics/ai/completions/{id}`,
  `GET /v2/api/sources/metrics/ai/completions/{id}/prompts`,
  `GET /v2/api/sources/metrics/ai/completions/reference-data` — never a POST
  that accepts a completion for ingest.
- **Verdict:** **unverifiable, with reason.** Reason: this spec does not
  cover the metering ingest surface, only its own read-back paths. What
  would be needed to verify: the ingest service's own OAS, which is a
  separate spec this repo does not have. The one witness this audit *does*
  have for this verb is negative, live evidence: the recorded HTTP 400 at
  `docs/comprehensive-roi-proof.md:191` (`Value 'AUX' is not valid. Allowed
  values: [CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER,
  TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO,
  VIDEO, IMAGE]`) — proof the ingest endpoint exists and validates
  `operationType` even though no OAS names it. The `--operation-type` value's
  *enum membership* (independent of the endpoint's existence) is checked
  against the platform spec's `AICompletionMetricResource` read-model schema
  by Phase 57 Plan 01's two-witness test — a corroborating, not a verifying,
  cross-check, since that schema describes the response shape, not this
  verb's request body.
- **Live evidence (D-11 capture 2, live host, 2026-09-03):** the reservation
  above is discharged. Host: the confirmed pre-prod multiplex VM this phase
  ran against (named by role, never by address, per this document's own
  redaction discipline). CLI: `revenium 1.5.0 (0f5f3a7)` — the same version
  named in `## Scope`.

  **Capture 1 — isolated two-arm proof, one variable changed.** Control arm
  (`--operation-type AUX`, the pre-fix value): exit `4`,
  `Error: Request failed (HTTP 400): Value 'AUX' is not valid. Allowed
  values: [CHAT, GENERATE, EMBED, CLASSIFY, SUMMARIZE, TRANSLATE, OTHER,
  TOOL_CALL, RERANK, SEARCH, MODERATION, VISION, TRANSFORM, GUARDRAIL, AUDIO,
  VIDEO, IMAGE]` — reproduces, live and in this session, the rejection
  recorded at `docs/comprehensive-roi-proof.md:191`. Fix arm
  (`--operation-type OTHER`, read live from the deployed `common.sh`
  constant, identical to the control arm in every other flag): exit `0`, no
  `HTTP 4`/`HTTP 5` text anywhere in the output. Tenant-side confirmation
  (a read-only `metrics completions` query, not a second write): the fix
  arm's row is present and queryable, carrying `operationType: OTHER`,
  `taskType: aux_title_generation`, `agent: Hermes`; the control arm's
  transaction id is absent from the tenant, exactly as expected of a
  rejected call that was never ingested.

  **Capture 2 — the shipped `report_auxiliary_usage` pass, through an
  ordinary per-minute cron tick, not a hand-built call.** Auxiliary metering
  was re-enabled through the documented `${STATE_DIR}/env` switch alone (the
  disabling line removed, its explanatory comment left intact); no file
  under the skill's `scripts/` directory was edited to make this succeed,
  re-confirmed by an unchanged `sha256sum` on `common.sh` and
  `hermes-report.sh` after the flip. The next cron-driven tick shipped
  auxiliary rows: 130 `Aux reported:` lines, 0 `Aux failed:` lines, 0
  `HTTP 400` occurrences anywhere in the tick — the previously measured
  130-failed-calls/minute storm did not recur. `revenium-aux.ledger` — absent
  on this host through every earlier capture — now carries its first `AUX:`
  lines ever: 130 of them, 100% labelled `aux_title_generation`. Two
  subsequent ticks over unchanged counters shipped zero new auxiliary
  invocations and appended zero new ledger lines — the live confirmation of
  the ledger's per-column subtraction idempotency, previously proven only in
  fixtures.

  **Predicted versus observed.** A prediction (142 invocations, 39,038
  auxiliary tokens, $0.0064146, 100% `aux_title_generation`) was written down
  and dated before the flip, together with a falsification band. Observed:
  130 invocations, 35,977 tokens, $0.005923, 100% `aux_title_generation`.
  Tokens, cost, and the per-task split all landed inside the written band.
  Invocation count landed below the written confirms floor (130 vs. 142) —
  stated here plainly as a partial mismatch, not rounded up to a full match,
  per this project's own precedent for recording an unsoftened result beside
  the passes. The shortfall was traced, not left as an open question: 12 of
  the 142 identities belong to sessions whose own main-loop token counters
  are zero, which structurally excludes them from the auxiliary pass's
  session-attribution cache — a scope boundary of the existing shipped
  code, not a behaviour this phase's fix introduced.

  **Standing limitation.** This is evidence about the ingest surface's
  *behaviour*: it accepts a spec-valid `operationType` value and rejects an
  invalid one, live, through both a hand-built call and the shipped cron
  path. It is not evidence about the surface's *schema* — that remains
  unverifiable until the ingest service's own OAS is available, and nothing
  above changes the verdict already stated for this row.

### `meter tool-event`

- **Invocation site:** `skills/revenium/scripts/tool-event-report.sh:136`.
- **OAS path:** **none among the 219** (same as `meter completion`). A
  read-back path exists — `GET /v2/api/sources/metrics/tool/events` — but no
  ingest path.
- **Verdict:** **unverifiable, with reason.** Reason: same as `meter
  completion` — this is the platform API spec, not the ingest service's own
  spec. What would be needed to verify: the same thing `meter completion`
  needs, the ingest service's own OAS.

### `guardrails enforcement-rules get`

- **Invocation site:** `skills/revenium/scripts/guardrail-check.sh:117`.
- **OAS path:** `GET /v2/api/ai/enforcement-rules/{teamId}`
- **Response schema:** `EnforcementRulesPayload` — no request body to check.
- **Path parameter:** `teamId`, matches the CLI's positional `<teamId>`
  argument (confirmed via `revenium guardrails enforcement-rules get --help`
  at 1.5.0: `Usage: revenium guardrails enforcement-rules get <teamId>`).
- **Verdict:** **compatible.**

### `guardrails budget-rules list`

- **Invocation site:** `skills/revenium/scripts/guardrail-check.sh:143-147`
  (the `BUDGET_RULES_CMD` array build and its invocation).
- **OAS path:** **no literally-named path.** No path or schema in the 219/442
  contains the string "budget".
- **Circumstantial candidate:** `GET /v2/api/ai/cost-controls`, response
  `CostControlPagedModel_Read` wrapping `CostControlResource_Read`.
- **Inference chain (assumption, D-08):**
  1. `CostControlResource_Read.id`'s OAS `example` value is the literal
     string `"jR2kmLs"` (confirmed this session by direct read of the
     schema).
  2. That exact same string, `jR2kmLs`, appears in this development
     machine's `revenium guardrails enforcement-events list --help` output
     at 1.5.0, as the example value for the **sibling** verb's `--rule-id`
     flag: `revenium guardrails enforcement-events list --rule-id jR2kmLs`
     (re-confirmed this session, not restated from research done against the
     stale local `1.4.0` CLI).
  3. `guardrail-check.sh:182`'s own comment independently describes
     `budget-rules list`'s return shape as `{id: <string-hash>, name: ...}`
     — matching `CostControlResource_Read`'s `id` (string) and `name`
     (string, nullable) fields.
  4. `CostControlResource_Read`'s other fields (`metricType`, `warnThreshold`,
     `hardLimit`, `windowType`, `action`) also match the vocabulary
     `guardrail-check.sh`'s own Python heredocs use when parsing
     `BUDGET_RULES_JSON` (`metricType`, `hardLimit`, `windowType` all appear
     as keys `guardrail-check.sh` reads from that response).

  Two independently-authored documents (the server's own OAS example, and
  the CLI's own `--help` text for a *different* verb) reusing one placeholder
  ID is strong evidence, not proof — the CLI verb name (`budget-rules list`)
  and the OAS path name (`cost-controls`) never literally match anywhere in
  either source. Scoring this row a full match on that evidence alone would
  be exactly the "witnesses that agree with each other" error this phase
  exists to correct (SSE-02 / adjacency, `57-02-PLAN.md`'s edge decision).

- **Verdict:** **unverifiable, with reason.** They touch, they do not merge:
  this is a named, sourced assumption, not a confirmed match. What would be
  needed to verify: either an OAS revision that names `budget-rules` (or
  `cost-controls`) explicitly as the CLI verb's backing resource, or a live
  capture correlating a `budget-rules list` response's `id` values against a
  `cost-controls` response's `id` values for the same team.

### `guardrails enforcement-events list`

- **Invocation site:** `skills/revenium/scripts/guardrail-check.sh:501-506`
  (the `EVENT_CMD` array).
- **OAS path:** `GET /v2/api/ai/enforcement-events`
- **Response schema:** `EnforcementEventPagedModel_Read`.
- **Query parameters (no request body to reconcile):** `teamId` (required),
  `ruleId`, `since`, `page`, `size`, `sort` — all present in the OAS. The
  CLI's own `--help` at 1.5.0 shows `--rule-id`, `--since`, `--page`,
  `--page-size` (`page-size` maps to the OAS's `size` param by description
  match, not a literal name match — worth naming, though this row's overall
  verdict does not depend on that one flag, since it is optional and this
  skill's own capability probe already gates sending it).
- **Verdict:** **compatible.**

### The marker-driven operationType sites (D-03)

Recorded, not guarded — this phase adds no runtime enum validator on any of
these paths. Four `--operation-type` emission sites exist in
`skills/revenium/scripts/`, confirmed by direct grep this session against the
tree as it stands **after** Phase 57 Plan 01's fix landed (the plan's own
planning-time line numbers, `hermes-report.sh:1246`/`3254`/`3420`, shifted by
Plan 01's comment insertions to the values below — the same shift Plan 01's
own `SoleOtherEmitterTests` had to correct for; this document cites the
current, post-shift lines rather than repeat the stale ones):

1. **`hermes-report.sh:1248`** — the auxiliary pass. Emits
   `--operation-type "${AUX_OPERATION_TYPE}"`, a named constant declared in
   `common.sh:343` that resolves to `OTHER` (Phase 57 Plan 01, D-01/D-02).
   `OTHER` is a member of the 17-value `operationType` enum, and its
   membership is the subject of Plan 01's dedicated two-witness test.
2. **`hermes-report.sh:3256`** — the per-marker path. Emits
   `--operation-type "${op_type}"`, sourced directly from a classifier-
   written marker record's `operation_type` field.
3. **`hermes-report.sh:3422`** — the zero-marker fallthrough. Emits a
   hardcoded `--operation-type "CHAT"` (WIRE-01 / D-22) for sessions with no
   marker file at all.
4. **`api-event-report.sh:1457`** — the event path's own `meter completion`
   call. Emits `--operation-type "${operation_type_r}"`, resolved from the
   same marker vocabulary. This site is named in **neither `57-CONTEXT.md`
   nor `57-RESEARCH.md`** — found during Phase 57 planning and carried
   forward into this audit row.

The classifier (`plugins/revenium-classifier/classifier.py`) writes exactly
two marker `operation_type` values: `GUARDRAIL` and `CHAT`. Both are members
of the 17-value enum, so sites 2 and 4 above never emit an off-enum value
today. `api-event-report.sh` additionally filters `GUARDRAIL` markers out of
its own event stream and falls back to `CHAT` for anything it does emit —
narrower than the marker path's own pass-through. No runtime enum validator
is added on any of these four sites this phase; D-03 is explicit that this
is an audited-not-guarded hazard, because the hazard is not currently live
(the classifier's own output vocabulary is a strict subset of the enum).

### Spec-quality caveat: the jobs-create request schema

Every one of `JobResource`'s 24 properties — including `name`, `type`,
`environment`, and `agenticJobId`, fields this skill's own `jobs create` call
plainly writes — is marked `readOnly: true` in the `2.20.0-SNAPSHOT` OAS
(confirmed this session by enumerating all 24 properties directly, not
restated from research). This is neither asserted as a pass nor as a
discrepancy here; it is an open question, in
`docs/evidence-class-precedence.md`'s idiom:

- **The fact:** `POST /v2/api/jobs`'s requestBody schema, `JobResource`, has
  no writable field by its own `readOnly` markers.
- **The likely explanation:** the create endpoint's request schema appears
  to reuse the read/response resource wholesale, an OAS-generation artifact
  rather than a genuine constraint. By contrast, the two outcome verbs'
  request schemas (`ReportOutcomeRequest_Read`, `UpdateOutcomeRequest_Read`)
  are clean write schemas — every field in both carries no `readOnly` marker
  at all, confirmed this session.
- **The counter-evidence:** this skill's own live-tenant proofs from Phase 40
  and Phase 52 show `--name`/`--type` values appearing correctly in
  `revenium jobs get` output for real jobs this skill created — direct
  evidence against the `readOnly` marker being enforced literally server-side.
- **Why this stays open:** that counter-evidence was **not re-run this
  session**. Re-confirming it live is a small, cheap check a future capture
  could add; until then, this caveat rides alongside `jobs create`'s
  *compatible* verdict above rather than either silently trusting the schema
  or silently ignoring the mismatch.

### Verdict summary

| Verb | OAS path | Verdict |
|---|---|---|
| `jobs create` | `POST /v2/api/jobs` | compatible (spec-quality caveat) |
| `jobs outcome` | `POST /v2/api/jobs/{agenticJobId}/outcome` | compatible |
| `jobs outcome-update` | `PATCH /v2/api/jobs/{agenticJobId}/outcome` | compatible |
| `meter completion` | none among 219 | unverifiable |
| `meter tool-event` | none among 219 | unverifiable |
| `guardrails enforcement-rules get` | `GET /v2/api/ai/enforcement-rules/{teamId}` | compatible |
| `guardrails budget-rules list` | none literally named; assumption: `GET /v2/api/ai/cost-controls` | unverifiable |
| `guardrails enforcement-events list` | `GET /v2/api/ai/enforcement-events` | compatible |
| marker-driven `operationType` sites (D-03) | n/a — audited, not guarded | n/a |

**No second actively-rejected request was found during this audit.** The
only confirmed, live server rejection in this repo's evidence is the one
this phase fixes (`docs/comprehensive-roi-proof.md:191`, `AUX` on `meter
completion`'s auxiliary pass). Had a second one turned up, it would have been
recorded here and surfaced to the operator as a scope call rather than fixed
unilaterally inside this phase (`57-CONTEXT.md`'s discrepancy-handling
recommendation); none did.

**On RESEARCH.md's Open Question 2** (whether the `jobs` verbs need a fresh
live call beyond schema comparison): schema-diff evidence, as tabulated
above, satisfies criterion 4's letter for the three `jobs` verbs the spec
covers cleanly. No new live call is required by any locked decision. Plan
57-05's live tick, which re-enables the auxiliary pass on the multiplex VM,
may produce an ordinary `jobs create` / `jobs outcome` call in the same
window as free corroboration — corroboration, not a requirement.
