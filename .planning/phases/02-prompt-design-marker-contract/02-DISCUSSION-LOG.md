# Phase 2: Prompt Design & Marker Contract - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-12
**Phase:** 02-prompt-design-marker-contract
**Areas discussed:** Halt-survivability E2E test plan, Seed taxonomy labels, Substantive-turn hard rule, SKILL.md section + reference-doc split

---

## Halt-survivability E2E test plan

### Q1: Session lengths
| Option | Description | Selected |
|--------|-------------|----------|
| Short + long (≈2k + ≈20k tokens) | Two scenarios — fresh baseline + dilution worst-case | ✓ |
| Short + mid + long (2k, 10k, 20k) | Three-point curve, ~50% more tester time | |
| Long only (≈20k tokens) | Worst-case only; no baseline comparison | |

**Notes:** Two-scenario coverage captures the failure mode without ballooning per-release test time.

### Q2: Models
| Option | Description | Selected |
|--------|-------------|----------|
| One Anthropic + one OpenAI | Sonnet 4.6 + GPT-4o-class; covers vendor-skew | ✓ |
| Anthropic only | Simpler but misses vendor-specific quirks | |
| Anthropic + OpenAI + Google | Three-vendor coverage, larger tester burden | |

**Notes:** Vendor-skew coverage justifies the second model; three-vendor was deferred as v1 overkill.

### Q3: Pass/fail criterion
| Option | Description | Selected |
|--------|-------------|----------|
| Verbatim halt string on first attempt, every run | Strict — any deviation = FAIL | ✓ |
| Verbatim within 3 attempts | Loose — masks the regression we're guarding against | |
| Halt-related response within 1 attempt | Loses contractual-string property | |

**Notes:** Strict criterion preserves the existing SKILL.md "ABSOLUTE FIRST" absolute framing.

### Q4: Location and cadence
| Option | Description | Selected |
|--------|-------------|----------|
| references/halt-survivability.md, run before each release | Plan ships, surfaced in CLAUDE.md/README | ✓ |
| Same file, run only after SKILL.md changes | Lighter cadence, blind to unrelated regressions | |
| Internal test plan in .planning/phases/02-*/ | Not discoverable to future contributors | |

**Notes:** Ships with the skill; surfaced so it can't be silently skipped on releases.

---

## Seed taxonomy labels

### Q1: code_review granularity
| Option | Description | Selected |
|--------|-------------|----------|
| Both review (general) and code_review (specific) | Analytics distinguish PR review from doc review | ✓ |
| review only — code_review folds in | Smaller surface, recover breakdown via secondary signals | |
| code_review only — drop generic review | Hermes-specific; lets other review forms mint as needed | |

### Q2: Final 8-label list
| Option | Description | Selected |
|--------|-------------|----------|
| research, analysis, generation, review, code_review, refactor, planning, debugging | 4 OpenLLMetry RFC + 4 Hermes extensions | ✓ |
| Same 8 + 'documentation' (drop 'generation') | Closer to Hermes use cases, loses RFC alignment | |
| Trim to 6 (drop both review labels) | Smaller surface; contradicts prior Q1 decision | |

### Q3: Per-label schema
| Option | Description | Selected |
|--------|-------------|----------|
| description + examples (TAX-02 shape) | Matches REQUIREMENTS verbatim; examples aid lookup-first | ✓ |
| description only | Lighter file, agent infers fit | |
| description + examples + aliases | Stronger anti-fragmentation but more complexity | |

### Q4: Mint policy
| Option | Description | Selected |
|--------|-------------|----------|
| Lookup-first, mint only when clearly no fit | Aligns with PROJECT.md decision 3 | ✓ |
| Conservative — explicit user trigger | Defeats agent-managed growth | |
| Liberal — mint whenever description could be tighter | Causes fragmentation (Pitfall 1) | |

---

## Substantive-turn hard rule

### Q1: Hard rule
| Option | Description | Selected |
|--------|-------------|----------|
| PITFALLS-recommended: tool call OR >200w OR multi-step reasoning | Verbatim PITFALLS Pitfall 2 mitigation | ✓ |
| Stricter: tool call (any non-read) OR >300w | Less false-positive, more false-negative | |
| Looser: tool call OR >100w OR borderline = classify | Invites Pitfall 2 over-classification | |

**Notes:** PITFALLS sentence carries the semantic guarantee; do not paraphrase downstream.

### Q2: Number of canonical examples
| Option | Description | Selected |
|--------|-------------|----------|
| 4 examples (2 clear + 2 borderline) | Matches PITFALLS guidance | ✓ |
| 3 examples (1 substantive + 1 trivial + 1 borderline) | Lighter inline block | |
| 2 examples | Minimal footprint, risks Pitfall 2 on borderline cases | |

### Q3: Uncertain-case behavior
| Option | Description | Selected |
|--------|-------------|----------|
| Skip — fall back to unclassified by NOT writing marker | PITFALLS-recommended; under-classification is recoverable | ✓ |
| Classify with closest existing label, never mint | Forces poor fit, mis-attributes tokens | |
| Always classify; mint if needed | Maximally aggressive; pollutes taxonomy | |

### Q4: Trivial-label blocklist
| Option | Description | Selected |
|--------|-------------|----------|
| ack, acknowledgment, greeting, confirmation, hello, thanks | Verbatim PITFALLS list | ✓ |
| Same + ok, yes, no, sure, noted | More defensive, bigger blocklist | |
| Minimal: ack, greeting, thanks | Expand only when fragmentation appears | |

**Notes:** Closed-set for v1; expansion requires a release.

---

## SKILL.md section + reference-doc split

### Q1: Insertion site
| Option | Description | Selected |
|--------|-------------|----------|
| After Verification, as final FINAL ACTION section | Max end-loaded; closing-discipline counterpart to halt-check | ✓ |
| Before References, after Script Entry Points | Mid-end; less 'final' | |
| Right after Budget Check Procedure | Mid-document; competes with halt anchor (Pitfall 7) | |

### Q2: Section heading framing
| Option | Description | Selected |
|--------|-------------|----------|
| "FINAL ACTION — TASK CLASSIFICATION" (closing-discipline) | Mirrors halt-check opening framing without using ABSOLUTE | ✓ |
| "After Your Response — Task Classification" | Softer, less likely to be read in long sessions | |
| "MANDATORY — TASK CLASSIFICATION" | Competes with the existing 'MANDATORY' in Budget Check | |

**Notes:** ABSOLUTE / FIRST / NON-NEGOTIABLE remain reserved for the halt-check.

### Q3: Content split between SKILL.md and references/task-taxonomy.md
| Option | Description | Selected |
|--------|-------------|----------|
| SKILL: rule + 4 examples + blocklist + snippet; references: schema + label catalog | Hot path inline, cold path in references | ✓ |
| SKILL: rule + 2 examples + snippet; references: everything else | Even more compact, but blocklist gets ignored without second read | |
| SKILL: rule + snippet only; references: rest | Minimal SKILL.md, max cron-side enforcement | |

### Q4: Snippet form
| Option | Description | Selected |
|--------|-------------|----------|
| Python heredoc (matches cron-side pattern) | Reuses fcntl/ULID stdlib idioms | ✓ |
| Bash printf into >> append | Smaller; loses ULID generation | |
| Both — python by default, bash as alternative | More flexible but doubles inline footprint | |

---

## Claude's Discretion

- Exact wording of the 4 canonical examples in SKILL.md (specific transcripts).
- Exact wording of each seed-label `description` field.
- Section structure of `references/task-taxonomy.md` (subsection ordering, formatting).
- Exact assertion text for the prompt-invariant test (PROMPT-07).

## Deferred Ideas

- `tools/audit-taxonomy.py` (V2-03) — taxonomy fragmentation auditor, deferred to v2.
- `scripts/show-recent-markers.sh` (V2-04) — operator debug helper, deferred to v2.
- Aliases array in per-label schema — rejected for v1, revisit if fragmentation forces it.
- Single-word affirmative blocklist expansion (`ok`, `yes`, `no`, `sure`, `noted`) — rejected for v1, expand only if Revenium-side data shows these labels.
- Closed-session marker rotation (V2-07) — deferred to v2.
- S3 / S4 split strategies — already deferred per PROJECT.md decision 5; pluggable seam ships in Phase 3.
