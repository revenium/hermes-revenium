# Security policy

This is beta, best-effort Revenium Labs software, not a supported security boundary.
Security fixes target the latest default-branch code; older pins require an explicit
upgrade after review. No response-time or backport SLA is promised.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/revenium/hermes-revenium/security/advisories/new)
if the repository exposes it. If that option is unavailable, contact Revenium through
[its official site](https://www.revenium.ai) and request a private security channel
before sharing details. Do not open a public issue containing an exploit, credentials,
customer data, transcripts or unredacted state files.

Include the commit SHA, Hermes/Python versions, affected install path, minimal
redacted reproduction and expected versus observed behavior. Do not send live keys.

## Trust and data boundaries

- The [catalog-only package](docs/catalog-install.md) and optional standalone bootstrap
  are different distributions. Review the [audit](docs/catalog-compliance-audit.md).
- The full integration reads Hermes session data and uses your configured model provider
  for classification. Its reporters transmit selected metadata, including some free text.
  See [What it sends where](README.md#what-it-sends-where).
- Shell guardrails depend on approved hooks and a periodically refreshed local snapshot.
  Missing or corrupt state fails open; this is not a hard real-time billing cap.
- Never run the bootstrap in a customer or production environment without operator review.
  Protect the CLI credential store and local assessment/state directories with host access controls.
- Use reviewed commit pins. Never paste secrets into issues, screenshots or demo recordings.
