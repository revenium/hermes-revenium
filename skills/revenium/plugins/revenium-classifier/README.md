# Revenium classifier — optional plugin-only distribution

The actual Revenium task/job classifier and per-API usage collector, packaged
without the full bootstrap. Install this directory at a reviewed exact commit;
no copied/alternate classifier implementation or runtime download is needed.
This is a catalog **candidate**, not a Nous-approved listing.

## What it does

- `classification_enabled: true`: classify substantive sessions into task/job
  labels using your configured Hermes auxiliary model, write local marker pairs,
  job records and completion sentinels, and maintain seeded taxonomies. Existing
  configured evaluation features may also produce assessment sidecars.
- `collection_enabled: true`: append per-API metadata and usage records locally.
  This is independent of classification and makes no extra model call.
- Fresh plugin-only installs default to neither behavior. Settings are fetched
  through public `ctx.get_config` on every event; explicit false disables even
  when the profile previously consented through a full installation.

Four Python hooks are registered: `on_session_end`, `on_session_finalize`,
`post_llm_call`, `post_api_request`. Registration itself does not classify or
collect. These are **not** the separately installed shell hooks.

## Data, permissions and operational disclosure

**Classification is not offline.** Once enabled it reads conversation content
from hook payloads and local session storage and sends excerpts to the configured
Hermes model provider via `agent.auxiliary_client.call_llm`. It can incur model
cost and synchronous completion-path latency. Classification/job inference,
rejudging uncertain jobs and configured outcome evaluation may make additional
calls; this is not a promise of only one call or one fixed deadline per turn.
The private-core import is disclosed: current validation warns about it but does
not reject it. Hermes releases can break this integration; a public model API
migration remains future work.

No Revenium API key is needed, no Revenium request is made, and this package does
not read `.env`, `auth.json`, vendor CLI credentials, browser stores or keychains.
Hermes owns provider credentials; the plugin calls its existing model helper
rather than retrieving keys itself. It reads non-secret Hermes `config.yaml`
for configured-model provenance and integration `state/revenium/config.json`
for settings. Path environment variables remain supported for existing installs;
they are settings, not credential access.

Profile resolution can read session **metadata** in `state.db` and profile homes
to locate the owning profile. When plugin settings are absent it probes that
profile's non-secret integration config for prior full-install consent. This
consent discovery is not transcript classification or usage collection. Explicit
false returns before that state-resolution probe. On fresh installs, absent or
malformed consent performs no model call, collection or state write.

Opted-in processing writes under the owning profile's `state/revenium/` (or
existing explicit path overrides): `markers/`, `.ready` sentinels, task/job/role
taxonomies, `api-events/`, and configured job-assessment sidecars. Session databases
are read-only. Bundled seeds are copied only when missing; learned values are
never overwritten. No shell processes, cron installer, background retention
worker, shell-hook registration, guardrail creation, exporter, code fetch or
self-updater is bundled. Monitor disk use and manage retention deliberately.

API-event records exclude prompt/response bodies, but include session/request
identifiers, model/provider, base URL, finish reason, timestamps and token counts.
Classification's generated job names, failure reasons and assessment text can
contain derived free text. They remain local **unless a separately installed
reporter consumes them**. Enabling classification is not consent to a fictional
"never any free text anywhere" guarantee. Do not place secrets in provider URLs
or other metadata. Hermes itself can log conversation/tool data and send it to
its configured provider independent of this plugin.

An already configured full integration retains prior consent when its owning
profile's config contains nonempty guardrail `ruleIds`, or an explicit
`pluginConsent` written by the full installer. This preserves full-install
behavior, including new metering-only installs. Old metering-only installs with
neither record require explicit plugin settings. Explicit false always wins.
Installing/removing this plugin does not turn independently configured reporting
or enforcement on/off. The plugin still respects an existing local halt snapshot
when classifying; without the separate polling/enforcement system this is not
live budget protection.

## Install, opt in, disable

See [the pinned plugin-only guide](../../../../docs/catalog-install.md). Requires
Hermes `>=0.23.3` (conservative tested floor), macOS/Linux (`fcntl`), standard
library Python and an already configured Hermes model if classification is wanted.
No full bootstrap or Revenium CLI is required. Use supported settings:

```sh
hermes config set plugins.entries.revenium-classifier.settings.classification_enabled true
hermes config set plugins.entries.revenium-classifier.settings.collection_enabled true
```

Set either to `false` to stop that behavior, or disable the whole plugin. Deleting
plugin code does not delete retained local records or stop external reporters.
Updates are a newly reviewed SHA, never a plugin self-update. License: MIT.
