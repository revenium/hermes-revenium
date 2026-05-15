---
phase: 7
slug: job-marker-schema-state-scaffolding
status: verified
threats_total: 3
threats_closed: 3
threats_open: 0
asvs_level: 1
created: 2026-05-15
---

# Phase 7 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| markers/&lt;sid&gt;.jsonl → cron reader | Agent-written JSONL lines are parsed by hermes-report.sh; this phase adds a new `kind` discriminator line to the existing file and reader. No new boundary — same file, same reader. | Per-session JSONL text, no credentials, no PII |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-07-01 | Tampering | `kind:"job"` line in `markers/<sid>.jsonl` | mitigate | See evidence below | closed |
| T-07-02 | Denial of Service | marker reader per-line loop | accept | See Accepted Risks Log | closed |
| T-07-03 | Information Disclosure | `revenium-jobs.ledger` (touch-created, empty) | accept | See Accepted Risks Log | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## T-07-01 Verification Evidence

**Disposition:** mitigate

**Mitigation plan:** Malformed / oversized / unknown-`kind` job lines are skipped, never fatal. The reader inherits the existing `try/except json.JSONDecodeError: continue` and 4 KB line cap, and unknown `kind` values hit the `elif kind is not None: continue` forward-compat skip (D-06). A job line missing any JOB_REQUIRED key is dropped, not raised (D-04). A WR-01/WR-03 gap found during execution (non-object JSON line raising AttributeError; unhashable `agentic_job_id` raising TypeError) was closed in commit 397003e before this audit.

**Code evidence — all patterns confirmed present in `skills/revenium/scripts/hermes-report.sh`:**

| Control | File:Line | Pattern Found |
|---------|-----------|---------------|
| 4 KB per-line cap | hermes-report.sh:397 | `if len(line) > 4096: continue` |
| JSONDecodeError catch + continue | hermes-report.sh:403 | `except json.JSONDecodeError: continue` |
| Non-object (list/scalar) skip guard (WR-01) | hermes-report.sh:408 | `if not isinstance(m, dict): continue` — positioned before any attribute access |
| kind branch before REQUIRED_KEYS check (D-06) | hermes-report.sh:414 | `kind = m.get("kind")` followed by `if kind == "job":` |
| agentic_job_id string validation (WR-03) | hermes-report.sh:419-420 | `job_id = m.get("agentic_job_id"); isinstance(job_id, str) and job_id` |
| JOB_REQUIRED membership check — missing-key drop (D-04) | hermes-report.sh:420 | `all(k in m for k in JOB_REQUIRED)` in same condition |
| continue after job branch — never reaches markers.append | hermes-report.sh:422 | `continue  # never reaches task-marker collector` |
| Unknown-kind forward-compat skip (D-06) | hermes-report.sh:423-424 | `elif kind is not None: continue` |

**Ordering verified:** `isinstance` guard (408) → `kind` branch (414) → `REQUIRED_KEYS` check (426). A hostile line cannot bypass any guard by reordering.

**Regression test coverage (TEST-02 Sub-case C, tests/test_repository.py:3765-3797):** Five malformed-line shapes (`[1,2,3]`, `"hello"`, `42`, `null`, list-valued `agentic_job_id`) each appended to a valid task-marker file; asserts that `meter completion` argv is byte-identical to the clean run for every shape.

**Verdict: CLOSED.**

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-07-02 | T-07-02 | Reader caps per-line memory at 4096 bytes (`hermes-report.sh:397`) and processes one line at a time. A hostile `kind:"job"` line cannot exceed v1.0's per-line cost — no new amplification. The marker file is a local-only file under `~/.hermes/state/revenium/` on a single-user host; the attack surface is the same as the existing v1.0 task-marker reader. | Auditor (gsd-security-auditor) | 2026-05-15 |
| AR-07-03 | T-07-03 | `revenium-jobs.ledger` is `touch`-created empty in `hermes-report.sh:35` under `~/.hermes/state/revenium/`, the same local-only state directory with the same OS-level permissions as every existing ledger (`revenium-hermes.ledger`, `revenium-metering.log`). No content is written to this file in Phase 7; it is scaffolding for Phase 9. Same information-disclosure posture as `revenium-hermes.ledger` (D-14: separate file, D-15: touch-created only). The env-var override names (`REVENIUM_JOBS_LEDGER_FILE`, `REVENIUM_JOB_TAXONOMY_FILE`) are confined to `common.sh` only, confirmed by grep. | Auditor (gsd-security-auditor) | 2026-05-15 |

---

## Unregistered Threat Flags

**SUMMARY.md `## Threat Flags` reports:** "None."

No new unregistered attack surface was identified during implementation beyond the three registered threats.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-15 | 3 | 3 | 0 | gsd-security-auditor (claude-sonnet-4-6) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-15
