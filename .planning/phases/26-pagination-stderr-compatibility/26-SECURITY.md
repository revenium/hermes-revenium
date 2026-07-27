---
phase: 26
slug: pagination-stderr-compatibility
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-27
---

# Phase 26 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Register origin: authored at plan time across all four PLAN.md `<threat_model>`
blocks (`register_authored_at_plan_time: true`). Verification mode was
mitigation-verification, not retroactive-STRIDE. Per the secure-phase
short-circuit rule, ASVS L1 grep-depth classification was sufficient — no
auditor subagent was spawned because `threats_open` resolved to 0 with a
plan-time register at L1.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| `revenium` CLI stdout/stderr → shell variable | Remote API text crosses into a shell variable, then into a JSON parser and an operator-facing log line | Remote error strings; possibly partial request parameters |
| local `PATH` → which `revenium` binary executes | Test harness deliberately shadows the real binary; a mis-placed stub means production code is never exercised | Test-fixture integrity (no runtime data) |
| `revenium` CLI stderr → `ENFORCEMENT_STDERR` → `grep` | Error text now captured into a named variable rather than discarded | Remote API error text |
| `ENFORCEMENT_STDERR` → `${STATE_DIR}/.cli-stderr.*` | Error text lands on disk for the duration of one run | Remote API error text |
| `guardrail-check.sh` → Revenium API (per minute, unattended) | The only outbound network boundary this phase widens | Budget/enforcement rule data |
| `budget-rules list` → `name_to_string_id` → `ruleId` | List content determines which id the halt-path event fetch uses | Operator's own rule names and ids |
| `rule_stderr` → `truncated_err` → `error()` → metering log | The one place captured stderr is deliberately surfaced to a human | Remote response text |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-26-01 | Tampering | `supports_flag` help-text capture (`common.sh`) | low | mitigate | `help_text` is `local`, quoted at every expansion, and only ever piped to `grep -qE`. No `eval`, no `source`, no unquoted interpolation — verified by inspection of `common.sh:120-140` and a negative grep for `eval`/`source` on the variable. | closed |
| T-26-02 | Spoofing | `PATH`-resolved `revenium` binary in tests | low | mitigate | Argv-log existence guard asserted before any content assertion (`tests/test_repository.py:11888`, `:12397`). A missing log proves the stub was bypassed and the real binary answered. | closed |
| T-26-03 | Denial of Service | per-tick `--help` probe spawn | low | accept | See Accepted Risks Log (R-01). | closed |
| T-26-04 | Tampering | captured stderr reaching an operator-facing message | low | mitigate | `ENFORCEMENT_STDERR` has exactly two references (`guardrail-check.sh:106` assignment, `:113` `grep -q` pipeline). It does not appear in `MSG=` (`:395`) or `SHADOW_MSG=` (`:428`) — verified by grep. Never `eval`'d, never passed to `hermes chat`. | closed |
| T-26-05 | Information Disclosure | `${STATE_DIR}/.cli-stderr.*` may briefly hold an API error containing partial credentials | low | accept | See Accepted Risks Log (R-02). | closed |
| T-26-06 | Denial of Service | over-broad EOF soft-fail masking a real outage | medium | mitigate | Pattern is exactly `'"error".*EOF'` at `guardrail-check.sh:113`, with an explicit do-not-widen comment at `:110`. Widening would report "no rules breached" during an API outage and enforcement would stop halting. | closed |
| T-26-07 | Denial of Service | per-minute `budget-rules list` under v1.3.0 all-pages aggregation | medium | mitigate | Bound stated in the `guardrail-check.sh` file header (`:12`) and enforced by `test_cron_tick_request_bound` using `assertEqual` — exact equality, not an upper bound (2 steady-state / 3 on halt). `REVENIUM_PAGE_BATCH_SIZE` defaults to 500 (`common.sh:64`). | closed |
| T-26-08 | Tampering | rule `name` as the only join key between integer and string id spaces | low | accept | See Accepted Risks Log (R-03). | closed |
| T-26-09 | Information Disclosure | `--page-size 500` widening the response body in `BUDGET_RULES_JSON` | low | accept | See Accepted Risks Log (R-04). | closed |
| T-26-10 | Tampering | `truncated_err` embedded into the `error()` log line | low | mitigate | Capped at 200 characters via `head -c 200` (`setup-guardrails.sh:491`), matching the existing T-18-LOG-INJECT truncate-before-embed convention. Passed only as a quoted argument to `error()`. | closed |
| T-26-11 | Information Disclosure | `${STATE_DIR}/.cli-stderr.*` in the setup path | low | accept | See Accepted Risks Log (R-05). | closed |
| T-26-12 | Spoofing | test stub shadowed by a real `revenium` binary (setup path) | medium | mitigate | `$HOME/.local/bin` + `env['HOME']` placement contract stated in `_make_setup_revenium_stub`'s docstring (`tests/test_repository.py:12410`), with the `ensure_path()` prepend-order rationale spelled out, plus argv-log existence guards. | closed |
| T-26-SC | Tampering | npm/pip/cargo installs | low | accept | See Accepted Risks Log (R-06). | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` (high) count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

No threat in this phase reaches `high`. The three `medium` findings (T-26-06,
T-26-07, T-26-12) are each mitigated in-task with an asserted control, not
merely intended.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-01 | T-26-03 | ~1 extra local process spawn per minute; the probe issues no HTTP request. A disk-cached alternative was considered and rejected in CONTEXT.md D-03 / Deferred Ideas — caching would reintroduce a staleness window and a concurrency surface the current design has none of. | CONTEXT.md D-03 | 2026-07-27 |
| R-02 | T-26-05 | `STATE_DIR` has no explicit mode restriction today (`common.sh` uses a bare `mkdir -p`), and `guardrail-status.json`'s writer sets no explicit permissions either. Pre-existing repo-wide posture, not introduced here. Incremental exposure is bounded by `mktemp`'s 0600 default and the EXIT trap that removes the file every run. A repo-wide `STATE_DIR` permissions decision belongs in its own phase. | Phase 26 plan 26-02 | 2026-07-27 |
| R-03 | T-26-08 | Duplicate rule names resolve last-write-wins. Accepted as pre-existing behavior and *pinned* by `test_duplicate_rule_names_resolve_to_last_listed_id` rather than changed — altering the collision policy is out of scope and needs its own decision. Names originate from the operator's own Revenium tenant, not an untrusted third party. | Phase 26 plan 26-03 | 2026-07-27 |
| R-04 | T-26-09 | Larger in-memory response, same data class as today (the operator's own budget rules). Never written to disk except as the derived `guardrail-status.json`, which already contains rule names and limits. | Phase 26 plan 26-03 | 2026-07-27 |
| R-05 | T-26-11 | Identical posture to R-02 in a second script. Bounded by `mktemp`'s 0600 default and a top-level EXIT trap that fires even on non-zero exit. | Phase 26 plan 26-04 | 2026-07-27 |
| R-06 | T-26-SC | Not applicable — this phase installs zero external packages. RESEARCH.md § "Package Legitimacy Audit" records N/A with no `[ASSUMED]`/`[SUS]`/`[SLOP]` entries, so no legitimacy checkpoint is required. | Phase 26 RESEARCH.md | 2026-07-27 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-27 | 13 | 13 | 0 | Claude (secure-phase, ASVS L1 grep-depth, short-circuit path) |

---

## Notes Carried Forward

Two items outside this register were raised during phase 26 verification and
explicitly accepted by the operator during UAT. Neither is a security threat,
but both are recorded here so they are not lost:

- **WR-01** (from `26-REVIEW.md`): a single `--help` capability probe result is
  reused to gate flags on *different* CLI verbs — in one case across command
  families (`guardrails` probe gating an `alerts budget list` call in
  `setup-guardrails.sh`). This is the design CONTEXT.md D-03 specifies. Accepted
  as-is; carried into Phase 30's live-host run where real CLI behavior becomes
  observable.
- **Two unmitigated `must_haves.prohibitions`**: no `warn` on
  `PAGE_FLAG_SUPPORTED=false` (silent capability degradation) and no
  truncation-detection when a wants-all-pages list returns exactly
  `REVENIUM_PAGE_BATCH_SIZE` rows (silent cap). Accepted for this milestone.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-27
