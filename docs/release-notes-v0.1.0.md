# v0.1.0 — draft release notes (not published)

**TODO(John): confirm version scope before tagging.** This repository already has v1.x
release history. `v0.1.0` is the requested draft label for the catalog/discoverability
package, not a claim that the existing integration is new or has been downgraded.
No tag or release is created by this change.

## Highlights

- Install-first README: per-job cost, value and ROI with budget guardrails; Labs/beta
  status retained and full-bootstrap effects disclosed before installation.
- Separate pinned catalog-only path, with a community-tier draft entry and audit.
  See [catalog installation](catalog-install.md) for its narrower capabilities.
- Explicit data destinations, local assessment-sidecar boundary and exceptions to
  “no model free-text”; model-estimated value is not verified savings.
- Demo GIF shot list, security reporting guidance and manual launch checklist.
- Value evaluator documentation now matches the existing 512-token response limit.

## Known limits / before release

- Full bootstrap remains optional and outside the catalog distribution; it fetches
  code and installs host cron/shell-hook configuration.
- Catalog acceptance requires Nous maintainer review and a real full 40-character
  commit pin in place of the draft placeholder. Local validation is not approval.
- Pricing/free-plan feature coverage is **TODO(John)**. The GIF is not recorded yet.
- Hosted installation and live ingestion have not been exercised by this documentation
  change. Follow the isolated demo plan rather than testing in customer environments.

## Manual launch checklist

- [ ] Apply proposed GitHub topics: `hermes-agent`, `hermes-plugin`, `ai-agents`,
      `llm-cost`, `finops`, `ai-finops`, `agent-observability`, `guardrails`, `roi`.
- [ ] Record and review `docs/demo.gif` using [the shot list](demo-script.md).
- [ ] Confirm free-plan versus paid features and replace `TODO(John)` in the README.
- [ ] Review/merge the draft PR, choose the version scope, then manually tag and
      publish the release; use a reviewed immutable commit for the catalog pin.
- [ ] Submit the pinned entry to NousResearch/hermes-agent and separately propose
      the project to awesome-hermes-agent, following each project's contribution rules.
