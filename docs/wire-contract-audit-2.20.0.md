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

