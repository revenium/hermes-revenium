# Catalog compliance audit — actual classifier, plugin-only path

## Decision

Use **`skills/revenium/plugins/revenium-classifier`** as the catalog subdirectory.
It contains the real classifier, dependent Python modules, taxonomy seeds and
consent gate at the reviewed pin.
No duplicate giant classifier, generated runtime payload or bootstrap dependency
is introduced. The full installer remains separate and optional.

This is a candidate, not catalog acceptance. The current validator accepts the
plugin with one private-core-import **warning**, not a rejection. A maintainer
must review that warning and the data-flow disclosures before admission.

## Official reference inspected

Read via `gh api` at official Hermes commit
`c7a3fe245d6bf610f73ff555d57e4ed632f8ded8`:

- [Catalog README/rules](https://github.com/NousResearch/hermes-agent/blob/c7a3fe245d6bf610f73ff555d57e4ed632f8ded8/plugin-catalog/README.md)
- [Langfuse](https://github.com/NousResearch/hermes-agent/blob/c7a3fe245d6bf610f73ff555d57e4ed632f8ded8/plugin-catalog/langfuse.yaml): explicit hook/credential capabilities, SHA, subdirectory and floor.
- [Mem0](https://github.com/NousResearch/hermes-agent/blob/c7a3fe245d6bf610f73ff555d57e4ed632f8ded8/plugin-catalog/mem0.yaml): content/backend and telemetry disclosures; its existing telemetry exception does not override today's opt-in rule.
- [Snyk](https://github.com/NousResearch/hermes-agent/blob/c7a3fe245d6bf610f73ff555d57e4ed632f8ded8/plugin-catalog/snyk.yaml): pinned dependency/transport and login disclosure; not permission for arbitrary credential-store reads.
- [Public API](https://github.com/NousResearch/hermes-agent/blob/c7a3fe245d6bf610f73ff555d57e4ed632f8ded8/website/docs/developer-guide/plugins/public-api.md) and plugin developer guide.

Latest release from GitHub: `v0.23.3`. Local validation CLI reports
`Hermes Agent v0.23.3 (2026.9.24) · stable · local caafe5389ae5`.
This is a local checkout, not proof of byte identity to official release source.
`requires_hermes: ">=0.23.3"` is the conservative tested floor, not a claim that
older releases cannot support any of these APIs. Final official CI is still due.

## Four primary installation-risk categories

These are actual executable source locations, not inferred README behavior.
All paths below are relative to this repository.

| Category | Source evidence | Catalog disposition |
|---|---|---|
| Runtime/bootstrap fetching | `skills/revenium/references/bootstrap.sh:25` defaults `REF` to `main`; `:52-54` fetches if runtime pieces are absent; `:70-72` clones the requested branch and falls back to the repository default; `:102` executes the fetched installer. | Excluded from the installed plugin subdirectory. The catalog path never calls this script. This bootstrap is **not an exact-SHA path**, even when a caller puts a commit-like value in its branch variable. |
| Updating/replacing installed code | `bootstrap.sh:37-46` accepts `--update`/`--refresh`; `:86-90` overlays scripts/plugins/seeds. `skills/revenium/scripts/install-plugin.sh:76-82` removes/replaces the installed plugin copy. | Standalone operator flows only. No self-updater or code fetch in the plugin; catalog updates must be reviewed SHA-bump PRs. |
| Scheduled reporting / cron persistence | `skills/revenium/scripts/install-cron.sh:133-143` constructs the command/environment; `:196` reads existing crontab; `:267` installs the new crontab using `crontab -`. `skills/revenium/scripts/install.sh:462-465` invokes it. | Excluded. Plugin-only capture writes local records; it neither schedules nor exports them. |
| Shell-hook and host-config writes | `skills/revenium/scripts/install-hooks.sh:119-121,220-231` selects/builds the pre-LLM/pre-tool/post-tool shell-hook commands; `:238,319,383` writes config. `:84-113` contains optional `hooks_auto_accept: true` mutation. `skills/revenium/scripts/install.sh:376-377` invokes hook installation and `:474` restarts the gateway. | Excluded. Four declared **Python plugin hooks** are not these shell-hook installers. No approval override/config write/restart occurs from plugin registration or execution. |

This separation is why the catalog entry points to the plugin directory, not the
repository root, `skills/revenium`, or a bootstrap skill. Downloading a pinned
repository via Hermes for installation is distinct from runtime self-updating.

## Candidate source and data-flow audit

Let `P = skills/revenium/plugins/revenium-classifier/` in this table.

| Concern | File:line evidence and verdict |
|---|---|
| Actual registered capabilities | `P/__init__.py:416-424` registers the four existing callbacks through consent wrappers. `P/plugin.yaml:6-13` declares no tools, exactly those hooks, no middleware and no credentials. Real capability probe matches. |
| Opt-in processing | `P/catalog_consent.py:18-34,53-74`: reads supported `ctx.get_config`; only boolean true enables explicit settings. Explicit false/malformed values stop before session/state resolution. Fresh absent consent produces no model call, collection or write. Settings rechecked per event. |
| Prior full-install consent | `P/catalog_consent.py:25-32` accepts explicit `pluginConsent` or existing nonempty configured `ruleIds` from the owning profile's non-secret config. `skills/revenium/scripts/install-plugin.sh:88-109` records consent when the operator deliberately runs the full installer, including new metering-only installs. Explicit plugin false overrides this fallback. Old metering-only installs with neither record require explicit settings; merely finding scripts does not grant consent. |
| Standalone taxonomy dependency | `P/catalog_consent.py:37-50` seeds bundled task/job/role JSON into the existing resolved state paths with exclusive-create, never overwriting learned taxonomy. `P/classifier.py:4597-4629,5190-5222,5440` consumes local taxonomy. Tests compare bundled seeds with canonical skill seeds. No runtime fetch or sibling skill dependency. |
| Other Python dependencies | Existing sibling modules remain in the same plugin directory, including `boundary_registry.py`, classification/evaluation/value/reporting helpers and API spool. `P/classifier.py:36` uses Hermes's auxiliary client. Standard library otherwise; `fcntl` requires macOS/Linux (catalog platforms declared). No pip/native downloads. |
| Session/profile/state access | `P/classifier.py:42-59` resolves existing path settings; `:124-127,362` defines/per-session-resolves paths. Consent discovery can read session ownership metadata/profile homes and integration config before deciding whether legacy consent exists. After opt-in the unchanged classifier reads transcript/session data and writes markers/assessments. It does not write Hermes's session DB. |
| Credential access | No plugin-owned credentials or `requires_env`. No `.env`, `auth.json`, vendor CLI login, browser profile or keychain reads in this package. `P/classifier.py:3514` reads non-secret Hermes model configuration for provenance, not a credential store. Path environment overrides are non-secret settings. Future direct API credentials must use `agent.secret_scope.get_secret` or the documented credentialed-provider route. |
| Core runtime override | Validator: `no runtime rebinds of Hermes core`. Public `ctx.register_hook`/`ctx.get_config` are used. Private import `P/classifier.py:36` remains an explicit compatibility warning; no monkeypatch or core table overwrite is introduced. |
| Model/network privacy | Enabling classification sends transcript excerpts to the user's configured model through the existing auxiliary helper (`P/classifier.py:5291` and other inference/evaluation calls). It costs tokens and can block completion hooks. It is **not offline**, even though no request goes directly to Revenium. |
| Local API capture | `P/__init__.py:306-380` excludes `response`/`assistant_message` from the spool call; `P/api_event_spool.py:63-68` gives the metadata/token allowlist; `:71-89` resolves owning-profile storage. Collection alone makes no model call. Identifiers/provider URL/finish reason remain metadata and should not contain secrets. |
| Indirect reporting and free text | This plugin has no exporter, but external existing reporters may consume shared state. Generated job names and failure reasons are not guaranteed free of sensitive text. Full-system examples: `skills/revenium/scripts/hermes-report.sh:4672,5682` sends job names, `skills/revenium/scripts/hermes-report.sh:7847-7848` carries failure reason, and `skills/revenium/scripts/tool-event-report.sh:633` sends tool errors. No blanket “never free text” guarantee is made. |
| Retention and failure behavior | No plugin-only cron/retention worker; local files can grow until managed. Consent wrapper fails closed and logs a fixed message, not exception content. Existing classifier callbacks retain their historical fail-open logging behavior, so local logs may contain detailed errors. |
| Pin and source review | `docs/catalog-entry.draft.yaml:4-5` deliberately has an invalid placeholder until a reviewed commit exists, then installs only the source subdirectory. Do not submit a branch/tag/short SHA. No generated bytecode should be staged. |

The manifest originally used `hooks` rather than `provides_hooks`; pre-change
validation failed for undeclared registrations. That is fixed. The auxiliary
private import warning was never itself a validation rejection.

## Verification and limitations

Commands actually executed (fixture tests isolate state and mock provider/CLI calls):

```sh
PYTHONDONTWRITEBYTECODE=1 hermes plugins validate skills/revenium/plugins/revenium-classifier --json
PYTHONDONTWRITEBYTECODE=1 hermes plugins validate skills/revenium/plugins/revenium-classifier --install-deps --json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_catalog_classifier tests.test_phase29_hook_registration tests.test_phase29_hook_dedup tests.test_repository -q
```

Validation: `ok: true`, schema valid, capability probe ran in isolation, all
declarations match, security scan `safe`, no core override. Exact warning:

```text
private core imports (catalog rule 9: public surfaces only; these can break on any release): classifier.py:36 agent.auxiliary_client.call_llm. Use ctx.* / documented plugin APIs, or open an issue for the seam you need.
```

The `--install-deps` run also returned passing validation but printed a separate
host dependency-preparation warning:

```text
dependency preparation failed: Plugin 'omh' requires hermes >=0.21.1,<0.22.0, running 0.23.3
```

No candidate dependency is declared. Do not call this a clean dependency-preparation
run: official clean CI must repeat it. No unrelated host plugin was modified.

The combined fixture/regression run returned:

```text
Ran 209 tests in 133.696s
FAILED (failures=1)
```

The sole failure was an intermediate README lacking
`--all-profiles`, in `test_docs_document_multi_profile_operation`; the classifier,
consent, real registered classification/capture, hook dedup and installer fixtures
passed. Existing ResourceWarnings and intentionally exercised failure-path logs
also appeared. The final README restores the missing flag; final verification is recorded in the PR.
This run is not the entire repository test suite. After adding explicit-null
rejection and a standalone-copy loading fixture, the focused final run returned
`Ran 44 tests in 0.298s` / `OK` across `test_catalog_classifier`,
`test_phase29_hook_registration` and `test_phase29_hook_dedup`.

New fixture coverage includes fresh default inactivity; strict booleans and
false-before-state-read; prior consent compatibility and false override; malformed
config fail-closed; independent collection; non-overwriting seed copies; live
setting revocation; actual registered classification writing a marker pair and
ready sentinel with a mocked LLM; and actual API capture proving body exclusion.

No actual catalog install, live model/Revenium API call, full bootstrap, host
configuration change, commit/push or catalog submission was performed. Installer
code was exercised only by existing isolated test fixtures; a standalone shell
syntax-check invocation was rejected by the host gateway safety guard because its
referenced installer mentions restart (no restart was attempted).

## Remaining admission gates

- Run the complete final-tree suite and review the full-installer consent persistence change.
- Commit/publish/review the code, replace the SHA placeholder, and validate that
  exact immutable tree with clean official Hermes.
- Review the private model API warning, legacy-consent migration semantics,
  transcript processing and shared-spool disclosures; passing scanner output is
  not blanket security approval.
- A separate human-reviewed upstream catalog entry is required for listing.
