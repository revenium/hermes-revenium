---
name: spike-findings-hermes-revenium
description: Implementation blueprint from spike experiments. Requirements, proven patterns, and verified knowledge for building hermes-revenium — specifically extracting task/job classification into a reusable library and governing the label taxonomy across hosts. Auto-loaded during implementation work.
---

<context>
## Project: hermes-revenium

**Idea: `portable-task-classifier`**

Task/job classification is wanted in Revenium contexts beyond Hermes — inside the LiteLLM
guardrail (to infer what arbitrary AI traffic is trying to accomplish), for Claude Code session
metering, and likely more. Today the only implementation is
`skills/revenium/plugins/revenium-classifier/classifier.py`, a 1166-line module welded to
Hermes' session DB, marker files, profile layout, and auxiliary LLM client. These spikes asked
whether it makes sense to extract the classification core into a generic Python library that
this plugin and non-Hermes hosts both consume — and if so, where exactly the seam is.

**The answer, in one line:** yes, extraction is safe and cheap (proven against the full test
suite), but it is the *least* consequential of three available interventions — **the asset is
the taxonomy, not the classifier code.**

Spike session wrapped: 2026-08-15

Prior art, different idea, not wrapped here:
`.planning/spikes/2026-08-13-plugin-interface-expansion/FINDINGS.md` — Hermes plugin-surface
findings (prompt sections freeze per session; `post_api_request` is a complete per-call metering
event; auxiliary usage is unmetered).
</context>

<requirements>
## Requirements

Non-negotiable design decisions from the `portable-task-classifier` idea. Every reference file
honors these.

- Extraction must be **behavior-preserving for Hermes**, not a rewrite. The existing 324-test
  suite is the bar, run against the real plugin file.
- The library imports **stdlib only** — no Hermes, no `agent.auxiliary_client`, no provider SDK.
  Hosts inject the model client.
- The log channel is part of the host contract, not an implementation detail
  (`tests/test_phase28_classifier_reject_log.py` pins the `revenium_classifier` logger and the
  lazy-`%r` rendering, T-28-07). Hosts inject their logger.
- The library takes exactly **four injection points**: model client, taxonomy store
  (`labels()`/`record()`), logger, and host name.
- Prompts are host-specific text (all three hardcode "Hermes"), so `host` is a parameter with a
  `"Hermes"` default — non-Hermes hosts run a different prompt and may produce different labels.
- Any future extraction must be validated by grafting the **real** plugin file and running the
  full suite: 5 of 7 seams are guarded only by tests that execute the file from its real path,
  invisible to an in-process `sys.path` graft.
- Every host must implement its own **"is this input substantive"** gate. The library
  classifies empty input without complaint.
- **The shared artifact that matters is the TAXONOMY, not the code.** Per-host taxonomy files
  re-pay cold-start drift per host and converge on different attractors; a served vocabulary
  does not.
- **Two attractors pull the classifier toward inapt labels, not one.** The seed vocabulary is
  one (`code_review` was emitted for a CI-flakiness item). The prompt's five hardcoded *"Good
  examples"* (`classifier.py:787`) are the other, and produced the more vivid failures —
  `sql_query_debug` and `prod_log_triage` were copied verbatim onto unrelated work. Spike 003
  originally blamed the seed for all of it; corrected in quick task 260815-r39.
- **Seed the vocabulary with a curated domain taxonomy**, and never seed a label the prompt's
  AVOID line names. Seed changes affect fresh installs only.
- **Do not change the prompt's examples without a temperature-0 instrument.** They demonstrably
  get copied AND they anchor the 2-4 word granularity (removing them: copying → 0, but labels in
  the target range 14/15 → 8/15). Measured effect sizes for one condition ranged 7%–40% across
  runs — that is harness noise, not signal.
- **Classify out of band, never on a request's critical path.** Inline classification adds a
  full model round-trip plus a vocabulary fetch to every request, and a classifier calling
  through the proxy it guards can be blocked by the halt rule it is enforcing.
</requirements>

<findings_index>
## Feature Areas

| Area | Reference | Key Finding |
|------|-----------|-------------|
| Classifier extraction | `references/classifier-extraction.md` | Extraction is behavior-preserving — 324/324 tests green through the library, 7/7 mutation seams killed — but the portable core is only ~24% of the module |
| Taxonomy governance | `references/taxonomy-governance.md` | Drift is cold-start, not intrinsic (0/4 reuse cold vs 8/8 warm). Shared vocabulary cuts cross-host disagreement 2.8 → 1.6 labels/item, but seed quality outranks it |
| Host integration | `references/host-integration.md` | Adapters are 22 (LiteLLM) and 56 (Claude Code) lines against a 228-line core; prompt cost is bounded at ~560 tokens; inline classification carries a halt-deadlock hazard |

## Effort ranking (from the measurements, not from taste)

1. **Curate the seed taxonomy** — costs nothing, needs no library and no service, fixes
   reproducible misclassification.
2. **Share the vocabulary across hosts** — worth ~1.2 labels per work item (2.8 → 1.6). Argues
   for a taxonomy *service*, independent of whether code is shared.
3. **Share the classifier code** — safe, small, provably behavior-preserving; least
   consequential of the three for the outcome the project cares about.

## Source Files

Original spike source is preserved in `sources/` — a complete, runnable `revenium_classify`
package plus every harness and raw result JSON.

| Path | What it is |
|------|-----------|
| `sources/001-extraction-seam/revenium_classify/` | The extracted library (stdlib-only, 4 modules) |
| `sources/001-extraction-seam/in_place_graft.py` | Full-suite validation with verified restore + `--mutate=` |
| `sources/001-extraction-seam/differential_test.py` | 4697-comparison equivalence harness |
| `sources/001-extraction-seam/analyze_split.py` | AST measurement of portable vs host-bound |
| `sources/002-host-fit/hosts/` | LiteLLM guardrail and Claude Code adapters |
| `sources/002-host-fit/serve_demo.py` | UI: one input, three host framings (port 8722) |
| `sources/003-taxonomy-drift/fragmentation.py` | Independent vs shared vocabulary experiment |
| `sources/004-inline-latency/measure.py` | Prompt growth, service hop, recursion analysis |
</findings_index>

<metadata>
## Processed Spikes

- 001-extraction-seam (VALIDATED)
- 002-host-fit (VALIDATED)
- 003-taxonomy-drift (VALIDATED)
- 004-inline-latency (PARTIAL)
</metadata>
