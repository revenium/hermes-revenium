# Deferred Items — Phase 01-path-foundation

## Pre-existing test failure (out of scope, scope-boundary deferred)

`python3 -m unittest tests.test_repository.RepositoryTests.test_no_legacy_branding_left` was
failing on `main` before Plan 01-01 work began. Four `.planning/` documentation files contain
case-folded substrings that match the legacy-branding regex enforced by
`tests/test_repository.py::test_no_legacy_branding_left`:

- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/phases/01-path-foundation/01-01-PLAN.md`

These are meta-references inside planning artifacts that quote the test's regex for
traceability — not real branding leakage in shipped runtime code under `skills/`,
`examples/`, or `tests/`. Plan 01-01's file scope is `skills/revenium/scripts/common.sh`,
`skills/revenium/scripts/install-cron.sh`, and `tests/test_repository.py`. Repairing the
test scope (e.g., having the legacy-branding test skip `.planning/`) or scrubbing the meta
references is not in scope for PATH-01/02/03 and should be handled by a separate cleanup
plan (likely Phase 5 "Housekeeping & Compat Hardening" or a dedicated meta-file scrub).

Documented per executor scope-boundary rule: only fix issues directly caused by the current
task's changes; log out-of-scope discoveries here. To avoid this deferred-items.md file
itself becoming an additional offender, the regex pattern is referenced abstractly here
rather than being quoted in full.
