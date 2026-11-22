# Optional pinned plugin-only classifier installation

The catalog candidate is the actual `revenium-classifier` in
`skills/revenium/plugins/revenium-classifier`, now self-contained with its taxonomy
seeds and opt-in controls. The existing classifier implementation is reused. This is a **candidate, not an approved or published catalog listing**.

## Reduced integration, not full bootstrap

This path supports task/job classification and local per-API usage capture. It
requires no Revenium CLI or API key and installs no cron, shell hooks, reporter,
budget rules or gateway restart. It does not fetch code at runtime or update
itself. Classification uses Hermes's configured auxiliary LLM, so **transcript
content goes to that model provider and can incur cost**. It is not offline.
Collection alone writes local metadata/token counts without model calls. Neither
mode sends anything directly to Revenium. Independently installed reporters can
consume these files; this plugin does not disable an existing integration.

See the [plugin disclosure](../skills/revenium/plugins/revenium-classifier/README.md)
for filesystem reads/writes, content handling, prior-consent compatibility,
retention, model latency and private-API risk.

## Review and install exactly one commit

Requires Hermes `>=0.23.3` (the tested floor), Python with `fcntl` (macOS/Linux),
and your existing Hermes model configuration only if classification is enabled.

After the implementation is committed and reviewed, replace the placeholder
below with its **full 40-character commit SHA**. Do not install the placeholder,
a branch or a moving tag. Confirm the intended profile (`HERMES_HOME`) first.

```sh
hermes plugins install revenium/hermes-revenium/skills/revenium/plugins/revenium-classifier \
  --ref REPLACE_WITH_REVIEWED_40_HEX_COMMIT_SHA --no-enable
```

No `install.sh`, `bootstrap.sh`, CLI credential setup or shell-hook/cron installer
is needed. Review validation warnings before enabling. To ensure fresh **and
previously bootstrapped** profiles start with both behaviors off:

```sh
hermes config set plugins.entries.revenium-classifier.settings.classification_enabled false
hermes config set plugins.entries.revenium-classifier.settings.collection_enabled false
hermes plugins enable revenium-classifier
```

Then opt into exactly the wanted behavior:

```sh
# Local per-API metadata/token usage capture; no extra model call:
hermes config set plugins.entries.revenium-classifier.settings.collection_enabled true
# Separately consent to transcript processing by your configured model:
hermes config set plugins.entries.revenium-classifier.settings.classification_enabled true
```

Settings are rechecked for every hook event. False overrides prior full-install
consent, so switching back to false stops future processing without reinstalling.
Start a new Hermes session after first installation to load the registered hooks.

### Verify without live billing/network probes

From the reviewed checkout:

```sh
hermes plugins validate skills/revenium/plugins/revenium-classifier --json
python3 -m unittest discover -s tests -p 'test_catalog*.py' -v
```

Fixture tests invoke the real registered hooks with mocked model responses and
isolated local state. They are not evidence of live-provider or Revenium delivery.
For an operator-authorized live check, inspect the owning profile's
`state/revenium/markers/` after substantive work, and `state/revenium/api-events/`
after a model API call with the corresponding setting enabled. No cron is needed
to create those files. No Revenium dashboard result is promised by this path.

## Prior full-install compatibility

When a setting is absent, existing configured nonempty `ruleIds` in the owning
profile's **non-secret** `state/revenium/config.json` preserve prior full-install
consent. The explicit full installer now records `pluginConsent` there as well,
including metering-only installs without rules. An explicit plugin false always
wins. Old metering-only installs with neither record need explicit settings or
a deliberate rerun of their managed installer; merely finding scripts is not
accepted as consent. Missing/corrupt config and malformed settings fail closed.

## Disable/remove and update

```sh
hermes plugins disable revenium-classifier
hermes plugins remove revenium-classifier
```

Removing code does not delete existing markers/usage metadata or stop separately
installed reporters/cron. Those are managed independently. Local capture has no
automatic retention worker; monitor disk use and manage retention deliberately.
For direct installs, review a new SHA and repeat the pinned install with `--force
--no-enable`. A future catalog listing updates only through reviewed SHA-bump PRs
and Hermes's update command; no plugin updater is shipped.

The draft [catalog entry](catalog-entry.draft.yaml) intentionally remains
non-installable until its pin is replaced. Human Nous review, final-pin validation
and clean dependency-preparation CI remain required; see the [audit](catalog-compliance-audit.md).
